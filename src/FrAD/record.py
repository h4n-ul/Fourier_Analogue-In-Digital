from .fourier import fourier
import os, struct, sys, zlib
import sounddevice as sd
from .tools.ecc import ecc
from .tools.headb import headb

class recorder:
    @staticmethod
    def record_audio(file_path, smprate = 48000, channels = None,
            bit_depth = 24,
            fsize: int = 2048,
            apply_ecc: bool = False, ecc_sizes: list = [128, 20],
            profile = 0, loss_level: int = 0, little_endian = False,
            meta = None, img: bytes | None = None):
        ecc_dsize, ecc_codesize = ecc_sizes

        segmax = ((2**31-1) // (((ecc_dsize+ecc_codesize)/ecc_dsize if apply_ecc else 1) * 256 * 16)//16)
        if fsize > segmax: raise ValueError(f'Sample size cannot exceed {segmax}.')
        if fsize < 2: raise ValueError(f'Sample size must be at least 2.')
        if fsize % 2 != 0: raise ValueError('Sample size must be multiple of 2.')
        if not 20 >= loss_level >= 0: raise ValueError(f'Invalid compression level: {loss_level} Lossy compression level should be between 0 and 20.')
        if profile == 2 and fsize%8!=0: raise ValueError(f'Invalid frame size {fsize} Frame size should be multiple of 8 for Profile 2.')
        if profile in [1, 2]:
            while True:
                x = input('\033[1m!!!Warning!!!\033[0m\nFourier Analogue-in-Digital is designed to be an uncompressed archival codec. Compression increases the difficulty of decoding and makes data very fragile, making any minor damage likely to destroy the entire frame. Proceed? (Y/N) ').lower()
                if x == 'y': break
                if x == 'n': sys.exit('Aborted.')

        print('Please enter your recording device ID from below.')
        for ind, dev in enumerate(sd.query_devices()):
            if dev['max_input_channels'] != 0:
                print(f'{ind} {dev['name']}')
                print(f'    srate={dev['default_samplerate']}\t channels={dev['max_input_channels']}')
        hw = int(input('> '))

        if channels is None: channels = sd.query_devices()[hw]['max_input_channels']

        # Setting file extension
        if not (file_path.lower().endswith('.frad') or file_path.lower().endswith('.dsin') or file_path.lower().endswith('.fra') or file_path.lower().endswith('.dsn')):
            if len(file_path) <= 8 and all(ord(c) < 128 for c in file_path): file_path += '.fra'
            else: file_path += '.frad'

        if os.path.exists(file_path):
            print(f'{file_path} Already exists. Proceed?')
            while True:
                x = input('> ').lower()
                if x == 'y': break
                if x == 'n': sys.exit('Aborted.')
        ecc_dsize, ecc_codesize = int(ecc_sizes[0]), int(ecc_sizes[1])
        print('Recording...')
        open(file_path, 'wb').write(headb.uilder(meta, img))

        record = sd.InputStream(samplerate=smprate, channels=channels, device=hw)
        record.start()
        with open(file_path, 'ab') as f:
            while True:
                try:
                    data = record.read(fsize)[0]
                    flen = len(data)
                    data, _, chnl, bf = fourier.analogue(data, bit_depth, channels, little_endian, profile=profile, smprate=smprate, level=loss_level)

                    # Applying ECC (This will make encoding hundreds of times slower)
                    if apply_ecc: data = ecc.encode(data, ecc_dsize, ecc_codesize)

                    efb = headb.encode_efb(profile, apply_ecc, little_endian, bf)
                    data = bytes(
                        #-- 0x00 ~ 0x0f --#
                            # Frame Signature
                            b'\xff\xd0\xd2\x97' +

                            # Segment length(Processed)
                            struct.pack('>I', len(data)) +

                            efb + # EFB
                            struct.pack('>B', chnl - 1) +                         # Channels
                            struct.pack('>B', ecc_dsize if apply_ecc else 0) +    # ECC DSize
                            struct.pack('>B', ecc_codesize if apply_ecc else 0) + # ECC code size

                            struct.pack('>I', smprate) +                       # Sample Rate

                        #-- 0x10 ~ 0x1f --#
                            b'\x00'*8 +

                            # Samples in a frame per channel
                            struct.pack('>I', flen) +

                            # ISO 3309 CRC32
                            struct.pack('>I', zlib.crc32(data)) +

                        #-- Data --#
                        data
                    )

                    # WRITE
                    f.write(data)

                except KeyboardInterrupt:
                    break
        record.close()
        print('Recording stopped.')
