class TunnelExpiredException(Exception):
    msg: str

    def __init__(self, msg: str = ""):
        self.msg = msg

class InvalidTunnelStateException(Exception):
    msg: str

    def __init__(self, msg: str = ""):
        self.msg = msg
