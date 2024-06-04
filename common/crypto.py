import json

from nacl.encoding import Base64Encoder
from nacl.public import PrivateKey, PublicKey, Box, EncryptedMessage

from common.models import SupportSecretBoxContents


def create_secret_box(priv: str, pub: str, json_str: str) -> EncryptedMessage:
    """ Creates a secret box given base64 encoded priv and pub keys, and 
        a string of hopefully json.
    """
    private_key = PrivateKey(priv.encode('ascii'), encoder=Base64Encoder)
    public_key = PublicKey(pub.encode('ascii'), encoder=Base64Encoder)
    box = Box(private_key, public_key)
    secret_box = box.encrypt(json_str.encode(
        encoding='ascii'), encoder=Base64Encoder)
    return secret_box


def open_secret_box(priv: str, pub: str, box: str) -> SupportSecretBoxContents:
    """ Opens a secret box, given base64 encoded priv and pub keys. """
    private_key = PrivateKey(priv.encode('ascii'), encoder=Base64Encoder)
    public_key = PublicKey(pub.encode('ascii'), encoder=Base64Encoder)
    b = Box(private_key, public_key)
    secret_box_str = b.decrypt(box.encode('ascii'), encoder=Base64Encoder).decode('utf-8')
    secret_box_dict = json.loads(secret_box_str)
    return SupportSecretBoxContents(**secret_box_dict)
