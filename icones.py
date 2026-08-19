"""
Biblioteca de ícones do aplicativo.

Todos os ícones são desenhados programaticamente com Pillow (não são
emojis) para garantir tamanho e estilo 100% consistentes entre botões,
independente da fonte de emoji do sistema operacional (que varia entre
Windows/Mac/Linux e é a causa mais comum de ícones desalinhados/com
tamanhos diferentes numa mesma barra de ferramentas).

Cada função de ícone desenha em uma tela 4x maior e reduz no final
(supersampling) para bordas suaves sem precisar de nenhuma dependência
extra além do Pillow (que o projeto já usa).
"""

from PIL import Image, ImageDraw

ESCALA = 4  # fator de supersampling para anti-aliasing manual


def _nova_tela(tamanho: int):
    tam_real = tamanho * ESCALA
    img = Image.new("RGBA", (tam_real, tam_real), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img), tam_real


def _finalizar(img: Image.Image, tamanho: int):
    return img.resize((tamanho, tamanho), Image.LANCZOS)


def _linha(desenho, p1, p2, cor, largura_base):
    desenho.line([p1, p2], fill=cor, width=largura_base * ESCALA, joint="curve")


def icone_pasta(tamanho=18, cor="#FFFFFF"):
    img, d, t = _nova_tela(tamanho)
    m = t * 0.12
    d.rounded_rectangle([m, t * 0.32, t - m, t - m], radius=t * 0.06, outline=cor, width=int(t * 0.07))
    d.rounded_rectangle([m, t * 0.18, t * 0.55, t * 0.34], radius=t * 0.05, outline=cor, width=int(t * 0.07))
    return _finalizar(img, tamanho)


def icone_imagem(tamanho=18, cor="#FFFFFF"):
    img, d, t = _nova_tela(tamanho)
    m = t * 0.12
    largura = int(t * 0.07)
    d.rounded_rectangle([m, m, t - m, t - m], radius=t * 0.08, outline=cor, width=largura)
    # sol/circulo
    raio = t * 0.09
    cx, cy = t * 0.32, t * 0.33
    d.ellipse([cx - raio, cy - raio, cx + raio, cy + raio], outline=cor, width=largura)
    # montanhas
    d.line([m + t * 0.06, t - m - t * 0.08, t * 0.42, t * 0.52, t * 0.62, t * 0.68], fill=cor,
           width=largura, joint="curve")
    d.line([t * 0.55, t * 0.62, t * 0.7, t * 0.45, t - m - t * 0.06, t - m - t * 0.08], fill=cor,
           width=largura, joint="curve")
    return _finalizar(img, tamanho)


def icone_ordenar_nome(tamanho=18, cor="#FFFFFF"):
    """Três linhas horizontais decrescentes + seta para baixo (ordenar lista)."""
    img, d, t = _nova_tela(tamanho)
    largura = int(t * 0.09)
    y0 = t * 0.20
    espaco = t * 0.20
    comprimentos = [t * 0.80, t * 0.58, t * 0.36]
    x0 = t * 0.10
    for i, comp in enumerate(comprimentos):
        y = y0 + i * espaco
        d.line([x0, y, x0 + comp, y], fill=cor, width=largura, joint="curve")
    return _finalizar(img, tamanho)


def icone_ordenar_data(tamanho=18, cor="#FFFFFF"):
    """Relógio simples (ordenar por data)."""
    img, d, t = _nova_tela(tamanho)
    largura = int(t * 0.08)
    m = t * 0.12
    d.ellipse([m, m, t - m, t - m], outline=cor, width=largura)
    cx, cy = t / 2, t / 2
    d.line([cx, cy, cx, t * 0.28], fill=cor, width=largura, joint="curve")
    d.line([cx, cy, t * 0.68, cy + t * 0.08], fill=cor, width=largura, joint="curve")
    return _finalizar(img, tamanho)


def icone_seta(direcao="esquerda", tamanho=18, cor="#FFFFFF"):
    img, d, t = _nova_tela(tamanho)
    largura = int(t * 0.10)
    if direcao == "esquerda":
        ponta = (t * 0.18, t * 0.5)
        d.line([t * 0.82, t * 0.5, ponta[0], ponta[1]], fill=cor, width=largura, joint="curve")
        d.line([ponta[0], ponta[1], t * 0.42, t * 0.26], fill=cor, width=largura, joint="curve")
        d.line([ponta[0], ponta[1], t * 0.42, t * 0.74], fill=cor, width=largura, joint="curve")
    else:
        ponta = (t * 0.82, t * 0.5)
        d.line([t * 0.18, t * 0.5, ponta[0], ponta[1]], fill=cor, width=largura, joint="curve")
        d.line([ponta[0], ponta[1], t * 0.58, t * 0.26], fill=cor, width=largura, joint="curve")
        d.line([ponta[0], ponta[1], t * 0.58, t * 0.74], fill=cor, width=largura, joint="curve")
    return _finalizar(img, tamanho)


def icone_lixeira(tamanho=18, cor="#FFFFFF", com_x=False):
    img, d, t = _nova_tela(tamanho)
    largura = int(t * 0.08)
    # tampa
    d.line([t * 0.18, t * 0.26, t * 0.82, t * 0.26], fill=cor, width=largura, joint="curve")
    d.line([t * 0.38, t * 0.26, t * 0.42, t * 0.14, t * 0.58, t * 0.14, t * 0.62, t * 0.26],
           fill=cor, width=largura, joint="curve")
    # corpo
    d.rounded_rectangle([t * 0.24, t * 0.28, t * 0.76, t * 0.88], radius=t * 0.06,
                         outline=cor, width=largura)
    if com_x:
        d.line([t * 0.38, t * 0.42, t * 0.62, t * 0.74], fill=cor, width=largura, joint="curve")
        d.line([t * 0.62, t * 0.42, t * 0.38, t * 0.74], fill=cor, width=largura, joint="curve")
    else:
        for x in (t * 0.38, t * 0.50, t * 0.62):
            d.line([x, t * 0.40, x, t * 0.76], fill=cor, width=largura, joint="curve")
    return _finalizar(img, tamanho)


def icone_documento(tamanho=18, cor="#FFFFFF"):
    """Página com canto dobrado (documento/capa)."""
    img, d, t = _nova_tela(tamanho)
    largura = int(t * 0.08)
    dobra = t * 0.28
    pontos = [
        (t * 0.24, t * 0.10), (t * 0.76 - dobra, t * 0.10), (t * 0.76, t * 0.10 + dobra),
        (t * 0.76, t * 0.90), (t * 0.24, t * 0.90), (t * 0.24, t * 0.10),
    ]
    d.line(pontos, fill=cor, width=largura, joint="curve")
    d.line([t * 0.76 - dobra, t * 0.10, t * 0.76 - dobra, t * 0.10 + dobra, t * 0.76, t * 0.10 + dobra],
           fill=cor, width=largura, joint="curve")
    for y in (t * 0.42, t * 0.56, t * 0.70):
        d.line([t * 0.34, y, t * 0.66, y], fill=cor, width=int(t * 0.05), joint="curve")
    return _finalizar(img, tamanho)


def icone_download(tamanho=20, cor="#FFFFFF"):
    """Seta apontando para baixo sobre uma bandeja/base - ícone clássico de download."""
    img, d, t = _nova_tela(tamanho)
    largura = int(t * 0.10)
    cx = t * 0.5
    # haste vertical da seta
    d.line([cx, t * 0.12, cx, t * 0.58], fill=cor, width=largura, joint="curve")
    # ponta da seta
    d.line([cx - t * 0.22, t * 0.38, cx, t * 0.62], fill=cor, width=largura, joint="curve")
    d.line([cx + t * 0.22, t * 0.38, cx, t * 0.62], fill=cor, width=largura, joint="curve")
    # bandeja/base
    d.line([t * 0.14, t * 0.78, t * 0.14, t * 0.88, t * 0.86, t * 0.88, t * 0.86, t * 0.78],
           fill=cor, width=largura, joint="curve")
    return _finalizar(img, tamanho)
