import hmac
import hashlib

# ============================================================
# Keccak-256 纯 Python 实现
# ============================================================
def keccak256(data):
    if isinstance(data, str):
        data = bytes.fromhex(data.replace("0x", ""))
    rate = 1088; output_len = 256; block_size = rate // 8
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % block_size != 0:
        padded.append(0x00)
    padded[-1] |= 0x80
    state = [[0]*5 for _ in range(5)]
    RC = [
        0x0000000000000001,0x0000000000008082,0x800000000000808A,
        0x8000000080008000,0x000000000000808B,0x0000000080000001,
        0x8000000080008081,0x8000000000008009,0x000000000000008A,
        0x0000000000000088,0x0000000080008009,0x000000008000000A,
        0x000000008000808B,0x800000000000008B,0x8000000000008089,
        0x8000000000008003,0x8000000000008002,0x8000000000000080,
        0x000000000000800A,0x800000008000000A,0x8000000080008081,
        0x8000000000008080,0x0000000080000001,0x8000000080008008
    ]
    ROT = [[0,36,3,41,18],[1,44,10,45,2],[62,6,43,15,61],
           [28,55,25,21,56],[27,20,39,8,14]]
    MASK64 = 0xFFFFFFFFFFFFFFFF
    def rot64(val, n):
        n = n % 64; return ((val << n) | (val >> (64 - n))) & MASK64
    def keccak_f(st):
        for rd in range(24):
            C = [st[x][0]^st[x][1]^st[x][2]^st[x][3]^st[x][4] for x in range(5)]
            D = [C[(x-1)%5]^rot64(C[(x+1)%5],1) for x in range(5)]
            for x in range(5):
                for y in range(5): st[x][y] ^= D[x]
            B = [[0]*5 for _ in range(5)]
            for x in range(5):
                for y in range(5): B[y][(2*x+3*y)%5] = rot64(st[x][y], ROT[x][y])
            for x in range(5):
                for y in range(5): st[x][y] = B[x][y] ^ ((~B[(x+1)%5][y]) & B[(x+2)%5][y])
            st[0][0] ^= RC[rd]
        return st
    for blk_start in range(0, len(padded), block_size):
        block = padded[blk_start:blk_start+block_size]; i = 0
        for y in range(5):
            for x in range(5):
                if i < block_size:
                    val = int.from_bytes(block[i:i+8], 'little') if i+8 <= len(block) else 0
                    state[x][y] ^= val; i += 8
        state = keccak_f(state)
    output = bytearray()
    for y in range(5):
        for x in range(5):
            output.extend(state[x][y].to_bytes(8, 'little'))
            if len(output) >= output_len // 8: return bytes(output[:output_len//8])
    return bytes(output[:output_len//8])

# ============================================================
# secp256k1 椭圆曲线
# ============================================================
P_CURVE = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8

def extended_gcd(a, b):
    if a == 0: return b, 0, 1
    g, x, y = extended_gcd(b % a, a); return g, y - (b // a) * x, x

def modinv(a, m=P_CURVE):
    if a < 0: a = a % m
    g, x, _ = extended_gcd(a, m)
    if g != 1: raise Exception("No modinv")
    return x % m

def point_add(p1, p2):
    if p1 is None: return p2
    if p2 is None: return p1
    x1, y1 = p1; x2, y2 = p2
    if x1 == x2 and y1 == y2: lam = (3*x1*x1*modinv(2*y1)) % P_CURVE
    elif x1 == x2: return None
    else: lam = ((y2-y1)*modinv(x2-x1)) % P_CURVE
    x3 = (lam*lam - x1 - x2) % P_CURVE
    y3 = (lam*(x1 - x3) - y1) % P_CURVE
    return (x3, y3)

def point_multiply(k, point=None):
    if point is None: point = (Gx, Gy)
    result = None; addend = point
    while k:
        if k & 1: result = point_add(result, addend)
        addend = point_add(addend, addend); k >>= 1
    return result

def private_key_to_address(pk_hex):
    if pk_hex.startswith("0x"): pk_hex = pk_hex[2:]
    pub = point_multiply(int(pk_hex, 16))
    pub_b = pub[0].to_bytes(32, 'big') + pub[1].to_bytes(32, 'big')
    return "0x" + keccak256(pub_b)[-20:].hex()

def public_key_to_address(pub_point):
    pub_b = pub_point[0].to_bytes(32, 'big') + pub_point[1].to_bytes(32, 'big')
    return "0x" + keccak256(pub_b)[-20:].hex()

# ============================================================
# RLP 编码
# ============================================================
def rlp_encode(v):
    if isinstance(v, bytes):
        if len(v) == 1 and v[0] < 0x80: return v
        return encode_length(len(v), 0x80) + v
    elif isinstance(v, int):
        if v == 0: return b'\x80'
        vb = v.to_bytes((v.bit_length()+7)//8, 'big')
        if len(vb) == 1 and vb[0] < 0x80: return vb
        return encode_length(len(vb), 0x80) + vb
    elif isinstance(v, list):
        out = b''.join(rlp_encode(i) for i in v)
        return encode_length(len(out), 0xc0) + out
    elif isinstance(v, str): return rlp_encode(v.encode())
    raise TypeError(f"Cannot RLP encode {type(v)}")

def encode_length(length, offset):
    if length < 56: return bytes([length + offset])
    bl = length.to_bytes((length.bit_length()+7)//8, 'big')
    return bytes([len(bl) + offset + 55]) + bl

# ============================================================
# 交易签名
# ============================================================
def hex_to_bytes(h):
    if h.startswith("0x"): h = h[2:]
    if len(h) % 2: h = "0" + h
    return bytes.fromhex(h)

def bytes_to_hex(b): return "0x" + b.hex()

def deterministic_k(msg_hash, pk_int):
    x = pk_int.to_bytes(32, 'big')
    h1 = msg_hash if isinstance(msg_hash, bytes) else bytes.fromhex(msg_hash)
    v = b'\x01' * 32; k_hmac = b'\x00' * 32
    k_hmac = hmac.new(k_hmac, v + b'\x00' + x + h1, hashlib.sha256).digest()
    v = hmac.new(k_hmac, v, hashlib.sha256).digest()
    k_hmac = hmac.new(k_hmac, v + b'\x01' + x + h1, hashlib.sha256).digest()
    v = hmac.new(k_hmac, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k_hmac, v, hashlib.sha256).digest()
        c = int.from_bytes(v, 'big')
        if 1 <= c < N_ORDER: return c
        k_hmac = hmac.new(k_hmac, v + b'\x00', hashlib.sha256).digest()
        v = hmac.new(k_hmac, v, hashlib.sha256).digest()

def recover_public_key(msg_hash, r, s, rid):
    try:
        y_sq = (pow(r, 3, P_CURVE) + 7) % P_CURVE
        y = pow(y_sq, (P_CURVE+1)//4, P_CURVE)
        if y % 2 != rid % 2: y = P_CURVE - y
        msg_int = int.from_bytes(msg_hash, 'big') if isinstance(msg_hash, bytes) else int(msg_hash, 16)
        r_inv = modinv(r, N_ORDER)
        sR = point_multiply(s, (r, y))
        eG = point_multiply(msg_int, (Gx, Gy))
        neg_eG = (eG[0], (P_CURVE - eG[1]) % P_CURVE)
        return point_multiply(r_inv, point_add(sR, neg_eG))
    except: return None

def sign_transaction(tx_dict, pk_hex, chain_id):
    if pk_hex.startswith("0x"): pk_hex = pk_hex[2:]
    pk_int = int(pk_hex, 16)
    items = [tx_dict["nonce"], tx_dict["gasPrice"], tx_dict["gas"],
             hex_to_bytes(tx_dict["to"]), tx_dict["value"],
             hex_to_bytes(tx_dict["data"]), chain_id, 0, 0]
    msg_hash = keccak256(rlp_encode(items))
    msg_int = int.from_bytes(msg_hash, 'big')
    k = deterministic_k(msg_hash, pk_int)
    point = point_multiply(k)
    r = point[0] % N_ORDER
    s = ((msg_int + r * pk_int) * modinv(k, N_ORDER)) % N_ORDER
    if s > N_ORDER // 2: s = N_ORDER - s
    rid = 0
    rec = recover_public_key(msg_hash, r, s, 0)
    if rec is None or public_key_to_address(rec).lower() != private_key_to_address("0x"+pk_hex).lower():
        rid = 1
    v = chain_id * 2 + 35 + rid
    signed = [tx_dict["nonce"], tx_dict["gasPrice"], tx_dict["gas"],
              hex_to_bytes(tx_dict["to"]), tx_dict["value"],
              hex_to_bytes(tx_dict["data"]), v, r, s]
    return bytes_to_hex(rlp_encode(signed))
