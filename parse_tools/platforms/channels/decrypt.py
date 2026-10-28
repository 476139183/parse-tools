"""Channels media decrypt (ISAAC64)."""

class ISAAC64:
    def __init__(self, key_uint64: int):
        self.rand_cnt = 255
        self.aa = 0
        self.bb = 0
        self.cc = 0
        self.seed = [0] * 256
        self.mm = [0] * 256
        self.seed[0] = key_uint64
        self.rand64_init()

    def mix(self, a, b, c, d, e, f, g, h):
        mask = 0xFFFFFFFFFFFFFFFF
        a = (a - e) & mask
        f = (f ^ (h >> 9)) & mask
        h = (h + a) & mask
        b = (b - f) & mask
        g = (g ^ ((a << 9) & mask)) & mask
        a = (a + b) & mask
        c = (c - g) & mask
        h = (h ^ (b >> 23)) & mask
        b = (b + c) & mask
        d = (d - h) & mask
        a = (a ^ ((c << 15) & mask)) & mask
        c = (c + d) & mask
        e = (e - a) & mask
        b = (b ^ (d >> 14)) & mask
        d = (d + e) & mask
        f = (f - b) & mask
        c = (c ^ ((e << 20) & mask)) & mask
        e = (e + f) & mask
        g = (g - c) & mask
        d = (d ^ (f >> 17)) & mask
        f = (f + g) & mask
        h = (h - d) & mask
        e = (e ^ ((g << 14) & mask)) & mask
        g = (g + h) & mask
        return a, b, c, d, e, f, g, h

    def rand64_init(self):
        golden = 0x9e3779b97f4a7c13
        a = b = c = d = e = f = g = h = golden
        for _ in range(4):
            a, b, c, d, e, f, g, h = self.mix(a, b, c, d, e, f, g, h)
        for i in range(0, 256, 8):
            a = (a + self.seed[i]) & 0xFFFFFFFFFFFFFFFF
            b = (b + self.seed[i+1]) & 0xFFFFFFFFFFFFFFFF
            c = (c + self.seed[i+2]) & 0xFFFFFFFFFFFFFFFF
            d = (d + self.seed[i+3]) & 0xFFFFFFFFFFFFFFFF
            e = (e + self.seed[i+4]) & 0xFFFFFFFFFFFFFFFF
            f = (f + self.seed[i+5]) & 0xFFFFFFFFFFFFFFFF
            g = (g + self.seed[i+6]) & 0xFFFFFFFFFFFFFFFF
            h = (h + self.seed[i+7]) & 0xFFFFFFFFFFFFFFFF
            a, b, c, d, e, f, g, h = self.mix(a, b, c, d, e, f, g, h)
            self.mm[i] = a; self.mm[i+1] = b; self.mm[i+2] = c; self.mm[i+3] = d
            self.mm[i+4] = e; self.mm[i+5] = f; self.mm[i+6] = g; self.mm[i+7] = h
        for i in range(0, 256, 8):
            a = (a + self.mm[i]) & 0xFFFFFFFFFFFFFFFF
            b = (b + self.mm[i+1]) & 0xFFFFFFFFFFFFFFFF
            c = (c + self.mm[i+2]) & 0xFFFFFFFFFFFFFFFF
            d = (d + self.mm[i+3]) & 0xFFFFFFFFFFFFFFFF
            e = (e + self.mm[i+4]) & 0xFFFFFFFFFFFFFFFF
            f = (f + self.mm[i+5]) & 0xFFFFFFFFFFFFFFFF
            g = (g + self.mm[i+6]) & 0xFFFFFFFFFFFFFFFF
            h = (h + self.mm[i+7]) & 0xFFFFFFFFFFFFFFFF
            a, b, c, d, e, f, g, h = self.mix(a, b, c, d, e, f, g, h)
            self.mm[i] = a; self.mm[i+1] = b; self.mm[i+2] = c; self.mm[i+3] = d
            self.mm[i+4] = e; self.mm[i+5] = f; self.mm[i+6] = g; self.mm[i+7] = h
        self.isaac64()

    def isaac64(self):
        self.cc = (self.cc + 1) & 0xFFFFFFFFFFFFFFFF
        self.bb = (self.bb + self.cc) & 0xFFFFFFFFFFFFFFFF
        for i in range(256):
            rem = i % 4
            if rem == 0:
                self.aa = (~(self.aa ^ (self.aa << 21))) & 0xFFFFFFFFFFFFFFFF
            elif rem == 1:
                self.aa = (self.aa ^ (self.aa >> 5)) & 0xFFFFFFFFFFFFFFFF
            elif rem == 2:
                self.aa = (self.aa ^ (self.aa << 12)) & 0xFFFFFFFFFFFFFFFF
            elif rem == 3:
                self.aa = (self.aa ^ (self.aa >> 33)) & 0xFFFFFFFFFFFFFFFF
            self.aa = (self.aa + self.mm[(i + 128) % 256]) & 0xFFFFFFFFFFFFFFFF
            x = self.mm[i]
            y = (self.mm[(x >> 3) % 256] + self.aa + self.bb) & 0xFFFFFFFFFFFFFFFF
            self.mm[i] = y
            self.bb = (self.mm[(y >> 11) % 256] + x) & 0xFFFFFFFFFFFFFFFF
            self.seed[i] = self.bb

    def isaac_random(self) -> int:
        result = self.seed[self.rand_cnt]
        if self.rand_cnt == 0:
            self.isaac64()
            self.rand_cnt = 255
        else:
            self.rand_cnt -= 1
        return result

def decrypt_channels_data(data: bytearray, key: int, enc_len: int = 131072):
    if len(data) == 0:
        return
    actual_enc_len = min(len(data), enc_len)
    aa_inst = ISAAC64(key)
    for i in range(0, actual_enc_len, 8):
        rand_num = aa_inst.isaac_random()
        temp_bytes = struct.pack(">Q", rand_num)
        for j in range(8):
            idx = i + j
            if idx >= actual_enc_len:
                return
            data[idx] ^= temp_bytes[j]



