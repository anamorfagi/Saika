# -*- coding: utf-8 -*-
"""Иконка ANAMORF: серебряная «А», собранная как нейрон.

Почему не SVG и не редактор: иконка обязана читаться и в 256, и в 16
пикселей, а это ДВЕ разные картинки, а не одна отмасштабированная. В
шестнадцати пикселях дендриты превращаются в грязь, обводка в кашу, узлы
в точки — поэтому мелкие размеры рисуются отдельным, огрублённым
чертежом. Скрипт держит оба чертежа в одном месте и собирает .ico целиком.
"""
from PIL import Image, ImageDraw, ImageFilter
import math, struct, io

SS = 4                      # суперсэмплинг: рисуем крупно, ужимаем в конце

def lerp(a, b, t): return tuple(round(x+(y-x)*t) for x, y in zip(a, b))

def silver(w, h):
    """Вертикальный металл. Серебро — это не серый цвет, а порядок полос:
    светлая кромка, тёмный провал, яркий отблеск ниже середины. Без
    провала между двумя светлыми полосами получается пластик."""
    stops = [(0.00,(232,236,241)), (0.20,(255,255,255)), (0.36,(184,191,201)),
             (0.54,(138,146,158)), (0.68,(214,220,228)), (0.84,(150,157,167)),
             (1.00,(122,129,139))]
    img = Image.new('RGB', (w, h)); px = img.load()
    for y in range(h):
        t = y/(h-1)
        for i in range(len(stops)-1):
            t0, c0 = stops[i]; t1, c1 = stops[i+1]
            if t0 <= t <= t1:
                c = lerp(c0, c1, (t-t0)/(t1-t0) if t1 > t0 else 0); break
        else: c = stops[-1][1]
        for x in range(w): px[x, y] = c
    return img

def plaque(S):
    """Тёмная подложка. Свет один и тот же во всём интерфейсе — сверху
    слева, поэтому верх плашки светлее низа, а по верхней кромке идёт
    тонкий блик."""
    img = Image.new('RGBA', (S, S), (0,0,0,0))
    d = ImageDraw.Draw(img)
    r = int(S*0.205)
    grad = Image.new('RGB', (1, S)); gp = grad.load()
    for y in range(S):
        t = y/(S-1)
        gp[0, y] = lerp((38,40,46), (12,13,16), t**0.8)
    grad = grad.resize((S, S))
    mask = Image.new('L', (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,S-1,S-1], r, fill=255)
    img.paste(grad, (0,0), mask)
    d.rounded_rectangle([1,1,S-2,S-2], r, outline=(255,255,255,38), width=max(2,S//170))
    return img

def glyph_mask(S, mode='full'):
    """Чертёж «А». Просто буква — никаких нейронов, отростков и узлов.

    Рисуется многоугольниками, а не линиями с круглыми концами: у линии
    торцы скругляются, и буква сразу перестаёт быть буквой — становится
    значком из трёх палок. У настоящей «А» торцы срезаны горизонтально, а
    вершина не остриё, а короткая площадка. Это то, что отличает литеру
    от треугольника, и на мелком размере видно первым.
    """
    m = Image.new('L', (S, S), 0)
    d = ImageDraw.Draw(m)
    k = S/1024.0
    # hw — половина ширины штриха, отмеренная ПО ГОРИЗОНТАЛИ. Отсюда сами
    # собой получаются горизонтальные срезы сверху и снизу.
    hw   = {'full':41, 'mid':50, 'min':66}[mode]*k
    top  = {'full':232, 'mid':238, 'min':244}[mode]*k
    by   = {'full':800, 'mid':796, 'min':790}[mode]*k
    cx   = 512*k
    lfx  = {'full':236, 'mid':244, 'min':252}[mode]*k
    rfx  = 1024*k - lfx
    bar  = {'full':.655, 'mid':.650, 'min':.645}[mode]
    bh   = {'full':60, 'mid':72, 'min':92}[mode]*k

    d.polygon([(cx-hw, top), (cx+hw, top), (lfx+hw, by), (lfx-hw, by)], fill=255)
    d.polygon([(cx-hw, top), (cx+hw, top), (rfx+hw, by), (rfx-hw, by)], fill=255)

    y  = top + (by-top)*bar
    t  = (y-top)/(by-top)
    xl = (cx-hw) + (lfx-hw-(cx-hw))*t
    xr = (cx+hw) + (rfx+hw-(cx+hw))*t
    d.polygon([(xl, y-bh/2), (xr, y-bh/2), (xr, y+bh/2), (xl, y+bh/2)], fill=255)
    return m

def render(size, mode='full'):
    S = size*SS
    img = plaque(S)
    m = glyph_mask(S, mode)

    sh = m.filter(ImageFilter.GaussianBlur(S*0.016))
    shadow = Image.new('RGBA', (S, S), (0,0,0,0))
    shadow.paste((0,0,0,190), (0, int(S*0.018)), sh)
    img = Image.alpha_composite(img, shadow)

    metal = silver(S, S).convert('RGBA')
    img = Image.alpha_composite(img, Image.composite(
        metal, Image.new('RGBA',(S,S),(0,0,0,0)), m))

    # Верхняя кромка буквы ловит свет — тонкая белая линия по контуру сверху.
    edge = Image.new('RGBA', (S, S), (0,0,0,0))
    up = m.filter(ImageFilter.MaxFilter(3))
    rim = Image.new('L', (S,S), 0)
    rim.paste(up, (0, -max(1, int(S*0.004))))
    from PIL import ImageChops
    rim = ImageChops.subtract(rim, m)
    edge.paste((255,255,255,120), (0,0), rim)
    img = Image.alpha_composite(img, edge)

    return img.resize((size, size), Image.LANCZOS)

# Три чертежа, а не один масштабированный: в 48 пикселях дендриты
# превращаются в царапины, а в 16 буква без утолщения просто исчезает.
def dib(im):
    """Одна картинка внутри .ico в формате BMP-с-маской.

    Пишется руками, потому что PIL сохраняет ВСЕ размеры PNG-ом, а Windows
    гарантированно понимает PNG внутри ico только для 256×256. Для мелких
    он ждёт BMP, и на PNG-варианте в части мест — панель задач, старые
    диалоги, некоторые списки — иконка просто не появляется. Пустое место
    вместо иконки выглядит как «программа сломана», хотя сломан формат.

    Высота в заголовке удвоена: так требует формат — за картинкой идёт
    однобитная маска прозрачности. Она нам не нужна (альфа уже в 32 битах),
    но её отсутствие ломает разбор, поэтому пишем нулями.
    """
    w, h = im.size
    px = im.convert('RGBA').load()
    hdr = struct.pack('<IiiHHIIiiII', 40, w, h * 2, 1, 32, 0, w * h * 4,
                      0, 0, 0, 0)
    rows = []
    for y in range(h - 1, -1, -1):          # BMP идёт снизу вверх
        row = bytearray()
        for x in range(w):
            r, g, b, a = px[x, y]
            row += bytes((b, g, r, a))      # и в порядке BGRA
        rows.append(bytes(row))
    mask_row = ((w + 31) // 32) * 4
    return hdr + b''.join(rows) + b'\x00' * (mask_row * h)


def write_ico(path, images):
    blobs = []
    for im in images:
        if im.width >= 256:
            b = io.BytesIO(); im.save(b, 'PNG'); blobs.append(b.getvalue())
        else:
            blobs.append(dib(im))
    off = 6 + 16 * len(images)
    out = struct.pack('<HHH', 0, 1, len(images))
    for im, data in zip(images, blobs):
        out += struct.pack('<BBBBHHII', im.width % 256, im.height % 256,
                           0, 0, 1, 32, len(data), off)
        off += len(data)
    open(path, 'wb').write(out + b''.join(blobs))


imgs = ([render(s, 'full') for s in (256, 128)] +
        [render(s, 'mid')  for s in (96, 64, 48)] +
        [render(s, 'min')  for s in (32, 24, 16)])
write_ico('ANAMORF.ico', imgs)
render(512, 'full').save('ANAMORF-512.png')
sheet = Image.new('RGBA', (256+128+96+64+48+32+24+16+9*12, 280), (18,18,21,255))
x = 12
for i in imgs:
    sheet.paste(i, (x, 20), i); x += i.width + 12
sheet.save('preview.png')
print('готово:', [i.width for i in imgs])
