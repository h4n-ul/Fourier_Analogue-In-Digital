from .common import variables, methods
from .fourier import fourier
import json, os, math, random, struct, subprocess, sys, time, traceback, zlib
import numpy as np
from .tools.ecc import ecc
from .tools.headb import headb

class encode:
    @staticmethod
    def get_info(file_path) -> tuple[int, int, str, int]:
        command = [variables.ffprobe,
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            file_path
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        info = json.loads(result.stdout)

        for stream in info['streams']:
            if stream['codec_type'] == 'audio':
                duration = stream['duration_ts'] * int(stream['sample_rate']) // int(stream['time_base'][2:])
                return int(stream['channels']), int(stream['sample_rate']), stream['codec_name'], duration
        print('No audio stream found.')
        sys.exit(1)

    @staticmethod
    def get_pcm_command(file_path: str, osr: int, new_srate: int | None, chnl: int | None) -> list[str]:
        command = [
            variables.ffmpeg,
            '-v', 'quiet',
            '-i', file_path,
            '-f', 'f64be',
            '-vn'
        ]
        if new_srate is not None and new_srate != osr:
            command.extend(['-ar', str(new_srate)])
        if chnl is not None:
            command.extend(['-ac', str(chnl)])
        command.append('pipe:1')
        return command

    @staticmethod
    def get_metadata(file_path: str):
        excluded = ['major_brand', 'minor_version', 'compatible_brands', 'encoder']
        command = [
            variables.ffmpeg, '-v', 'quiet', '-y',
            '-i', file_path,
            '-f', 'ffmetadata',
            variables.meta
        ]
        subprocess.run(command)
        with open(variables.meta, 'r', encoding='utf-8') as m:
            meta = m.read()
        metadata_lines = meta.split('\n')[1:]
        metadata = []
        current_key = None
        current_value = []

        for line in metadata_lines:
            if '=' in line:
                if current_key:
                    metadata.append([current_key, '\n'.join(current_value).replace('\n\\\n', '\n')])
                current_key, value = line.split('=', 1)
                if current_key in excluded:
                    current_key = None
                else:
                    current_value = [value]
            elif current_key:
                current_value.append(line)

        if current_key:
            metadata.append([current_key, '\n'.join(current_value)])
        os.remove(variables.meta)
        return metadata

    @staticmethod
    def get_image(file_path: str):
        command = [
            variables.ffmpeg, '-v', 'quiet', '-i', file_path,
            '-an', '-vcodec', 'copy',
            '-f', 'image2pipe', '-'
        ]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        image, _ = process.communicate()
        return image

    @staticmethod
    def enc(file_path: str, bits: int, **kwargs):
        # FrAD data specification
        fsize: int = kwargs.get('fsize', 2048)
        little_endian: bool = kwargs.get('le', False)
        profile: int = kwargs.get('prf', 0)
        loss_level: int = kwargs.get('lv', 0)
        gain: float = kwargs.get('gain', None)

        # ECC settings
        apply_ecc: bool = kwargs.get('ecc', False)
        ecc_sizes: tuple[int, int] = kwargs.get('ecc_sizes', [128, 20])
        ecc_dsize: int = ecc_sizes[0]
        ecc_codesize: int = ecc_sizes[1]

        # Audio settings
        new_srate: int = kwargs.get('srate', None)
        chnl: int = kwargs.get('chnl', None)

        # Raw PCM
        raw: str = kwargs.get('raw', None)

        # Metadata
        meta: list[list[str]] = kwargs.get('meta', None)
        img: bytes = kwargs.get('img', None)

        # CLI
        verbose: bool = kwargs.get('verbose', False)
        out: str = kwargs.get('out', None)

        methods.cantreencode(open(file_path, 'rb').read(4))

        # Forcing sample rate and channel count for raw PCM
        if raw:
            if new_srate is None: print('Sample rate is required for raw PCM.'); sys.exit(1)
            if chnl is None: print('Channel count is required for raw PCM.'); sys.exit(1)
            channels, smprate = chnl, new_srate
        if not 20 >= loss_level >= 0: print(f'Invalid compression level: {loss_level} Lossy compression level should be between 0 and 20.'); sys.exit(1)
        if profile in [1, 2]:
            print('\033[1m!!!Warning!!!\033[0m\nFourier Analogue-in-Digital is designed to be an uncompressed archival codec. Compression increases the difficulty of decoding and makes data very fragile, making any minor damage likely to destroy the entire frame. Proceed? (Y/N)')
            while True:
                x = input('> ').lower()
                if x == 'y': break
                if x == 'n': sys.exit('Aborted.')
        # Getting Audio info w. ffmpeg & ffprobe
        if not raw:
            channels, smprate, codec, duration = encode.get_info(file_path)
            if new_srate is not None: duration = int(duration / smprate * new_srate)
        segmax = (2**31-1) // (((ecc_dsize+ecc_codesize)/ecc_dsize if apply_ecc else 1) * channels * 16)//16
        if fsize > segmax: print(f'Sample size cannot exceed {segmax}.'); sys.exit(1)

        # Getting command and new sample rate
        if not raw: cmd = encode.get_pcm_command(file_path, smprate, new_srate, chnl)
        smprate = new_srate is not None and new_srate or smprate

        if out is None: out = os.path.basename(file_path).rsplit('.', 1)[0]

        if meta == None and not raw: meta = encode.get_metadata(file_path)
        if img == None and not raw: img = encode.get_image(file_path)

        # Setting file extension
        if not out.lower().endswith(('.frad', '.dsin', '.fra', '.dsn')):
            if profile == 0:
                if len(out) <= 8 and all(ord(c) < 128 for c in out): out += '.fra'
                else: out += '.frad'
            else:
                if len(out) <= 8 and all(ord(c) < 128 for c in out): out += '.dsn'
                else: out += '.dsin'

        if os.path.exists(out):
            print(f'{out} Already exists. Proceed?')
            while True:
                x = input('> ').lower()
                if x == 'y': break
                if x == 'n': sys.exit('Aborted.')

        # Fourier Transform
        try:
            start_time = time.time()
            total_bytes, total_samples = 0, 0
            cli_width = 40

            last = b''
            dtype, sample_bytes = methods.get_dtype(raw)
            smpsize = sample_bytes * channels # Single sample size = bit depth * channels

            # Open FFmpeg
            if not raw: process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
            else:
                rfile = open(file_path, 'rb')
                duration = os.path.getsize(file_path) / smpsize

            # Write file
            open(out, 'wb').write(headb.uilder(meta, img))
            with open(out, 'ab') as file:
                if verbose: print('\n\n')
                while True:
                    # bits = random.choice([12, 16, 24, 32, 48, 64]) # Random bit depth test
                    # fsize = random.choice(list(range(32, 8193))) # Random spf test
                    # profile = random.choice(list(range(2))) # Random profile test
                    # loss_level = random.choice(list(range(21))) # Random lossy level test
                    # apply_ecc = random.choice([True, False]) # Random ECC test
                    # ecc_dsize, ecc_codesize = random.choice(list(range(64, 129))), random.choice(list(range(16, 64))) # Random ECC test

                    # Getting required read length
                    rlen = fsize * smpsize
                    spf = fsize
                    while rlen < len(last):
                        spf += 128
                        rlen = spf * smpsize
                    # Overlap
                    if profile in [1, 2] and len(last) != 0: rlen -= len(last)

                    if not raw:
                        if process.stdout is None: raise FileNotFoundError('Broken pipe.')
                        data = process.stdout.read(rlen)   # Reading PCM
                    else: data = rfile.read(rlen)          # Reading RAW PCM
                    if not data: break                     # if no data, Break

                    # 1/16 linear Overlap
                    if len(last) != 0: data = last + data
                    if profile in [1, 2]: last = data[-fsize//16*8*channels:]
                    else: last = b''

                    # RAW PCM to Numpy
                    frame = np.frombuffer(data[:len(data)//smpsize * smpsize], dtype).astype(float).reshape(-1, channels) * gain
                    if raw:
                        if not raw.startswith('f'):
                            frame /= 2**(sample_bytes*8-1)
                            if raw.startswith('u'): frame-=1
                    flen = len(frame)

                    # DCT
                    frame, bit_depth_frame, channels_frame, bits_efb = \
                        fourier.analogue(frame, bits, channels, little_endian, profile=profile, smprate=smprate, level=loss_level)

                    # Applying ECC
                    if apply_ecc: frame = ecc.encode(frame, ecc_dsize, ecc_codesize)

                    # EFloat Byte
                    efb = headb.encode_efb(profile, apply_ecc, little_endian, bits_efb)

                    data = bytes(
                        #-- 0x00 ~ 0x0f --#
                            # Frame Signature
                            b'\xff\xd0\xd2\x97' +

                            # Frame length(Processed)
                            struct.pack('>I', len(frame)) +

                            efb + # ECC-Float Byte
                            struct.pack('>B', channels_frame - 1) +              # Channels
                            struct.pack('>B', apply_ecc and ecc_dsize or 0) +    # ECC DSize
                            struct.pack('>B', apply_ecc and ecc_codesize or 0) + # ECC Code Size

                            # Sample Rate
                            struct.pack('>I', smprate) +

                        #-- 0x10 ~ 0x1f --#
                            b'\x00'*8 +

                            # Samples in a frame per channel
                            struct.pack('>I', flen) +

                            # ISO 3309 CRC32
                            struct.pack('>I', zlib.crc32(frame)) +

                        #-- Data --#
                        frame
                    )

                    # WRITE
                    file.write(data)

                    if verbose:
                        sample_size = bit_depth_frame // 8 * channels
                        total_bytes += flen * sample_size
                        total_samples += flen
                        if profile in [1, 2]:
                            total_bytes -= flen//16 * sample_size
                            total_samples -= flen//16
                        elapsed_time = time.time() - start_time
                        bps = total_bytes / elapsed_time
                        mult = bps / smprate / sample_size
                        percent = total_samples / duration * 100
                        prgbar = int(percent / 100 * cli_width)
                        eta = (elapsed_time / (percent / 100)) - elapsed_time if percent != 0 else 'infinity'
                        print('\x1b[1A\x1b[2K\x1b[1A\x1b[2K\x1b[1A\x1b[2K', end='')
                        print(f'Encode Speed: {(bps / 10**6):.3f} MB/s, X{mult:.3f}')
                        print(f'elapsed: {methods.tformat(elapsed_time)}, ETA {methods.tformat(eta)}')
                        print(f"[{'█'*prgbar}{' '*(cli_width-prgbar)}] {percent:.3f}% completed")

                if verbose: print('\x1b[1A\x1b[2K', end='')
        except KeyboardInterrupt:
            print('Aborting...')
            sys.exit(0)
        except Exception as e:
            if verbose: print('\x1b[1A\x1b[2K\x1b[1A\x1b[2K\x1b[1A\x1b[2K', end='')
            sys.exit(traceback.format_exc())
