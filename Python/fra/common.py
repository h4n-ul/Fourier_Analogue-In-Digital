import base64, math, os, platform, secrets

class variables:
    nperseg = int
    hash_block_size = 2**20

    dir = os.path.dirname(os.path.realpath(__file__))
    temp = os.path.join(dir, f'temp.{base64.b64encode(secrets.token_bytes(64)).decode().replace("/", "_")}.swv')
    temp2 = os.path.join(dir, f'temp.ecc.{base64.b64encode(secrets.token_bytes(64)).decode().replace("/", "_")}.swv')
    temp_pcm = os.path.join(dir, f'temp.{base64.b64encode(secrets.token_bytes(64)).decode().replace("/", "_")}.pcm')
    temp2_pcm = os.path.join(dir, f'temp.rate.{base64.b64encode(secrets.token_bytes(64)).decode().replace("/", "_")}.pcm')
    temp_flac = os.path.join(dir, f'temp.{base64.b64encode(secrets.token_bytes(64)).decode().replace("/", "_")}.flac')
    meta = os.path.join(dir, f'{base64.b64encode(secrets.token_bytes(64)).decode().replace("/", "_")}.meta')

    oper = platform.uname()
    arch = platform.machine().lower()

    if oper.system == 'Windows' and arch in ['amd64', 'x86_64']:
        ffmpeg = os.path.join(dir, 'res', 'codec', 'ffmpeg.Windows')
        aac = os.path.join(dir, 'res', 'codec', 'AppleAAC.Windows')
        ffprobe = os.path.join(dir, 'res', 'parser', 'ffprobe.Windows')
    elif oper.system == 'Darwin':
        ffmpeg = os.path.join(dir, 'res', 'codec', 'ffmpeg.macOS')
        aac = 'afconvert'
        ffprobe = os.path.join(dir, 'res', 'parser', 'ffprobe.macOS')
    else:
        if arch in ['amd64', 'x86_64']:
            ffmpeg = os.path.join(dir, 'res', 'codec', 'ffmpeg.AMD64')
            ffprobe = os.path.join(dir, 'res', 'parser', 'ffprobe.AMD64')
        if arch == 'arm64':
            ffmpeg = os.path.join(dir, 'res', 'codec', 'ffmpeg.AArch64')
            ffprobe = os.path.join(dir, 'res', 'parser', 'ffprobe.AArch64')

class ecc_v:
    data_size = 128
    block_size = math.ceil(1.15*data_size)
    code_size = block_size - data_size

class methods:
    def signature(sign):
        if sign != b'\x16\xb0\x03':
            raise Exception('This is not Fourier Analogue file.')

    def get_ecc():
        pass