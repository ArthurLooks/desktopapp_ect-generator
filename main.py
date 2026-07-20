import os
import re
import sys
import threading
import traceback
from datetime import datetime

import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageOps

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader

# ---------------------------------------------------------------------------
# Suporte opcional a Drag and Drop (tkinterdnd2). Se a biblioteca não estiver
# instalada, o app funciona normalmente, apenas sem o recurso de arrastar
# arquivos do Explorer/Finder direto para a janela.
# ---------------------------------------------------------------------------
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False


EXTENSOES_VALIDAS = (".png", ".jpg", ".jpeg", ".bmp", ".gif")

TAMANHO_THUMB = 150          # tamanho FIXO (px) da área de miniatura em todo cartão
COLUNAS_GALERIA = 4          # número fixo de colunas na grade de cartões
LARGURA_CARTAO = 168         # largura de cada cartão (px), incluindo espaçamento
COR_LETTERBOX = ("#dbdbdb", "#2b2b2b")  # fundo (claro, escuro) da moldura da miniatura
COR_BORDA_NORMAL = "gray30"
COR_BORDA_SELECIONADA = "#3B8ED0"
NOME_ARQUIVO_ICONE = "favicon.ico"  # precisa estar na mesma pasta do script/exe

# Configuração visual básica (leve, sem dependências pesadas)
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


def caminho_do_recurso(nome_arquivo: str):
    """
    Resolve o caminho de um arquivo auxiliar (como o ícone) tanto quando o
    app roda via 'python gerador_ect.py' quanto quando roda como .exe
    empacotado pelo PyInstaller (--onefile extrai os arquivos embutidos
    para uma pasta temporária apontada por sys._MEIPASS).
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, nome_arquivo)


# ---------------------------------------------------------------------------
# Funções utilitárias (puras, sem dependência de estado da UI)
# ---------------------------------------------------------------------------

def natural_sort_key(caminho_arquivo: str):
    """
    Gera uma chave de ordenação 'natural' baseada no nome do arquivo.
    Isso garante que 'evidencia2.png' venha antes de 'evidencia10.png'
    (diferente da ordenação alfabética padrão, que colocaria 10 antes de 2).
    """
    nome = os.path.basename(caminho_arquivo)
    partes = re.split(r"(\d+)", nome)
    chave = [int(parte) if parte.isdigit() else parte.lower() for parte in partes]
    return chave


def sort_key_data_criacao(caminho_arquivo: str):
    """Chave de ordenação baseada na data de criação/modificação do arquivo."""
    try:
        # getctime nem sempre é 'data de criação real' em todos os SOs,
        # mas é o valor mais confiável disponível de forma multiplataforma.
        return os.path.getctime(caminho_arquivo)
    except OSError:
        return 0


def listar_imagens_da_pasta(pasta: str):
    """Retorna todos os arquivos de imagem válidos dentro de uma pasta."""
    arquivos = []
    for nome in os.listdir(pasta):
        if nome.lower().endswith(EXTENSOES_VALIDAS):
            arquivos.append(os.path.join(pasta, nome))
    return arquivos


def calcular_dimensoes_ajustadas(largura_img, altura_img, largura_max, altura_max):
    """
    Calcula o tamanho final da imagem para caber dentro da área disponível
    da página, preservando a proporção original (sem cortar/distorcer).
    """
    escala = min(largura_max / largura_img, altura_max / altura_img)
    return largura_img * escala, altura_img * escala


def truncar_nome(nome: str, tamanho_max: int = 20) -> str:
    """Encurta nomes de arquivo longos para caber no cartão, mantendo a extensão."""
    if len(nome) <= tamanho_max:
        return nome
    base, ext = os.path.splitext(nome)
    disponivel = tamanho_max - len(ext) - 1
    return f"{base[:disponivel]}…{ext}"


def texto_no_plural(quantidade: int, singular: str, plural: str) -> str:
    """Retorna '<n> <singular>' ou '<n> <plural>' de acordo com a quantidade."""
    return f"{quantidade} {singular if quantidade == 1 else plural}"


# ---------------------------------------------------------------------------
# Classe principal da aplicação
# ---------------------------------------------------------------------------

# Se tkinterdnd2 estiver disponível, a janela precisa herdar de TkinterDnD.Tk
# combinado com CustomTkinter. Esse é o padrão recomendado para usar as duas
# bibliotecas juntas.
if DND_AVAILABLE:
    class JanelaBase(TkinterDnD.DnDWrapper, ctk.CTk):
        def __init__(self):
            super().__init__()
            self.TkdndVersion = TkinterDnD._require(self)
else:
    class JanelaBase(ctk.CTk):
        pass


class GeradorECTApp(JanelaBase):
    def __init__(self):
        super().__init__()

        self.title("Gerador de ECT - Evidências de Caso de Teste")
        self.geometry("920x680")
        self.minsize(820, 560)

        # Ícone da janela e da barra de tarefas (não é o mesmo ícone do
        # arquivo .exe - esse é definido na hora de gerar o executável com
        # a flag --icon do PyInstaller). Se o arquivo não existir, o app
        # continua funcionando normalmente, só sem ícone customizado.
        try:
            self.iconbitmap(caminho_do_recurso(NOME_ARQUIVO_ICONE))
        except Exception:
            pass

        # Lista interna que guarda apenas os CAMINHOS dos arquivos (strings),
        # na ordem final em que vão para o PDF.
        self.lista_imagens = []

        # Cache de miniaturas já geradas (path -> CTkImage), para não
        # reprocessar a imagem toda vez que a lista é reordenada.
        self.cache_thumbnails = {}

        # Cartões atualmente na tela: caminho -> {"frame":, "badge":}.
        # Mantido entre atualizações para não destruir/recriar cartões que
        # já existem (evita o "piscar" da galeria a cada seleção/reordenação
        # - só o que realmente muda em cada cartão é atualizado).
        self._cartoes = {}

        # Estado de seleção/arraste da galeria. A seleção é guardada pelo
        # CAMINHO do arquivo (não pelo índice), assim ela continua
        # acompanhando a imagem certa mesmo depois de reordenar a lista.
        self.selecionados = set()
        self._widget_para_caminho = {}     # mapeia widgets -> caminho do cartão
        self._caminho_ultimo_click = None  # para seleção por intervalo (shift+click)
        self._arrastando_caminho = None
        self._arraste_em_progresso = False
        self._pos_inicial_mouse = (0, 0)

        self._montar_interface()

    # ------------------------------------------------------------------
    # Construção da interface
    # ------------------------------------------------------------------
    def _montar_interface(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._montar_cabecalho()
        self._montar_botoes_topo()
        self._montar_dica_dnd()
        self._montar_galeria()
        self._montar_rodape()

    def _montar_cabecalho(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            frame, text="ID / Nome do Caso de Teste:", font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, padx=(12, 8), pady=12, sticky="w")

        self.entry_titulo = ctk.CTkEntry(
            frame, placeholder_text="Ex: TC-1234 - Login com usuário válido"
        )
        self.entry_titulo.grid(row=0, column=1, padx=(0, 12), pady=12, sticky="ew")

    def _montar_botoes_topo(self):
        """
        Barra de ferramentas em DUAS linhas para garantir que nenhum texto de
        botão seja cortado, independentemente do tamanho da janela. Todos os
        botões usam cursor de "mão" (pointer) ao passar o mouse por cima.
        """
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(4, 0))

        linha1 = ctk.CTkFrame(frame, fg_color="transparent")
        linha1.pack(fill="x", pady=(0, 4))
        linha2 = ctk.CTkFrame(frame, fg_color="transparent")
        linha2.pack(fill="x")

        botoes_linha1 = [
            ("📁  Selecionar Pasta", self.selecionar_pasta),
            ("🖼️  Adicionar Arquivos", self.adicionar_arquivos),
            ("🔤  Ordenar por Nome", lambda: self.ordenar_automaticamente("nome")),
            ("🕒  Ordenar por Data", lambda: self.ordenar_automaticamente("data")),
        ]
        # "Mover Antes/Depois" substitui o antigo "Mover Cima/Baixo": numa
        # galeria em grade (várias colunas), "cima/baixo" não descreve bem
        # o movimento real do cartão. "Antes/Depois" fala da ORDEM da
        # evidência na sequência final do PDF, que é o que importa aqui -
        # a reordenação livre continua disponível arrastando o cartão.
        botoes_linha2 = [
            ("◀  Mover Antes", self.mover_antes),
            ("Mover Depois  ▶", self.mover_depois),
            ("🗑️  Remover Selecionados", self.remover_selecionado),
            ("🧹  Remover Todos", self.remover_todos),
        ]

        for texto, comando in botoes_linha1:
            ctk.CTkButton(
                linha1, text=texto, command=comando, width=205, height=34, cursor="hand2"
            ).pack(side="left", padx=4)
        for texto, comando in botoes_linha2:
            ctk.CTkButton(
                linha2, text=texto, command=comando, width=205, height=34, cursor="hand2"
            ).pack(side="left", padx=4)

    def _montar_dica_dnd(self):
        texto_dnd = (
            "💡 Arraste imagens do Explorador de Arquivos direto para a galeria abaixo, "
            "ou clique/arraste um cartão para reordenar."
            if DND_AVAILABLE
            else "💡 Clique e arraste um cartão para reordenar manualmente. "
            "(Arrastar do Explorador de Arquivos indisponível - instale tkinterdnd2)"
        )
        ctk.CTkLabel(self, text=texto_dnd, text_color="gray", anchor="w").grid(
            row=2, column=0, sticky="ew", padx=20, pady=(6, 0)
        )

    def _montar_galeria(self):
        """Área rolável com os cartões (miniatura + número + nome) de cada imagem."""
        self.galeria = ctk.CTkScrollableFrame(self, label_text="Evidências carregadas")
        self.galeria.grid(row=3, column=0, sticky="nsew", padx=16, pady=8)
        for col in range(COLUNAS_GALERIA):
            self.galeria.grid_columnconfigure(col, weight=1)

        # Área de drop de arquivos externos (Explorer/Finder).
        # IMPORTANTE: o CTkScrollableFrame é composto de vários widgets
        # internos sobrepostos (um Canvas que hospeda a área rolável e um
        # CTkFrame externo para a borda). Dependendo de onde exatamente o
        # cursor solta o arquivo, o sistema operacional pode entregar o
        # evento de drop a qualquer um desses widgets - por isso registramos
        # o mesmo destino em vários pontos (janela principal, galeria e seu
        # canvas interno) para garantir que o drop seja capturado em
        # qualquer lugar da tela.
        if DND_AVAILABLE:
            alvos_de_drop = [self, self.galeria]
            canvas_interno = getattr(self.galeria, "_parent_canvas", None)
            if canvas_interno is not None:
                alvos_de_drop.append(canvas_interno)

            for alvo in alvos_de_drop:
                alvo.drop_target_register(DND_FILES)
                alvo.dnd_bind("<<Drop>>", self._ao_soltar_arquivos)

    def _montar_rodape(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=4, column=0, sticky="ew", padx=16, pady=(4, 16))
        frame.grid_columnconfigure(0, weight=1)

        self.label_status = ctk.CTkLabel(frame, text="Nenhuma imagem carregada.", anchor="w")
        self.label_status.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.progress_bar = ctk.CTkProgressBar(frame)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self.botao_gerar = ctk.CTkButton(
            frame,
            text="📄  Gerar ECT (PDF)",
            command=self.iniciar_geracao_pdf,
            height=42,
            font=ctk.CTkFont(size=15, weight="bold"),
            cursor="hand2",
        )
        self.botao_gerar.grid(row=2, column=0, sticky="ew")

    # ------------------------------------------------------------------
    # Ações de carregamento de arquivos (sempre via diálogo NATIVO do SO)
    # ------------------------------------------------------------------
    def selecionar_pasta(self):
        # filedialog.askdirectory já invoca a janela nativa do sistema
        # operacional (Explorador de Arquivos no Windows, Finder no macOS).
        # O parâmetro parent garante que o diálogo fique corretamente
        # vinculado/em foco sobre a janela principal do app.
        pasta = filedialog.askdirectory(title="Selecione a pasta com as evidências", parent=self)
        if not pasta:
            return
        novos = listar_imagens_da_pasta(pasta)
        if not novos:
            messagebox.showinfo("Aviso", "Nenhuma imagem (PNG/JPG) foi encontrada nessa pasta.")
            return
        self._adicionar_arquivos_a_lista(novos)

    def adicionar_arquivos(self):
        # filedialog.askopenfilenames também é a janela nativa do SO.
        arquivos = filedialog.askopenfilenames(
            title="Selecione as imagens de evidência",
            filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp *.gif"), ("Todos os arquivos", "*.*")],
            parent=self,
        )
        self._adicionar_arquivos_a_lista(list(arquivos))

    def _ao_soltar_arquivos(self, event):
        # tkinterdnd2 retorna os caminhos em uma string; splitlist trata
        # corretamente espaços e chaves em nomes de arquivo/pasta
        caminhos = self.tk.splitlist(event.data)
        arquivos_validos = []
        for caminho in caminhos:
            if os.path.isdir(caminho):
                arquivos_validos.extend(listar_imagens_da_pasta(caminho))
            elif caminho.lower().endswith(EXTENSOES_VALIDAS):
                arquivos_validos.append(caminho)
        self._adicionar_arquivos_a_lista(arquivos_validos)

    def _adicionar_arquivos_a_lista(self, novos_arquivos):
        if not novos_arquivos:
            return
        # Evita duplicados mantendo a ordem
        for caminho in novos_arquivos:
            if caminho not in self.lista_imagens:
                self.lista_imagens.append(caminho)

        self._atualizar_status("Gerando prévias das imagens...")
        self.update_idletasks()

        # Ordenação automática por nome (natural sort) ao carregar,
        # conforme requisito de ordenação cronológica padrão
        self.ordenar_automaticamente("nome", mostrar_status=False)
        self._atualizar_galeria()
        self._atualizar_status()

    # ------------------------------------------------------------------
    # Ordenação
    # ------------------------------------------------------------------
    def ordenar_automaticamente(self, criterio="nome", mostrar_status=True):
        if not self.lista_imagens:
            return
        if criterio == "nome":
            self.lista_imagens.sort(key=natural_sort_key)
        elif criterio == "data":
            self.lista_imagens.sort(key=sort_key_data_criacao)
        self.selecionados.clear()
        self._atualizar_galeria()
        if mostrar_status:
            self._atualizar_status(f"Lista reordenada por {criterio}.")

    # ------------------------------------------------------------------
    # Ordenação manual / remoção via botões (trabalham sobre self.selecionados,
    # que agora guarda CAMINHOS de arquivo, não posições - por isso não é
    # mais necessário recalcular a seleção depois de mover: o item
    # selecionado continua sendo "ele mesmo" onde quer que pare na lista).
    # ------------------------------------------------------------------
    def mover_antes(self):
        indices = sorted(self.lista_imagens.index(c) for c in self.selecionados)
        if not indices or indices[0] == 0:
            return
        for i in indices:
            self.lista_imagens[i - 1], self.lista_imagens[i] = (
                self.lista_imagens[i],
                self.lista_imagens[i - 1],
            )
        self._atualizar_galeria()

    def mover_depois(self):
        indices = sorted((self.lista_imagens.index(c) for c in self.selecionados), reverse=True)
        if not indices or indices[0] == len(self.lista_imagens) - 1:
            return
        for i in indices:
            self.lista_imagens[i + 1], self.lista_imagens[i] = (
                self.lista_imagens[i],
                self.lista_imagens[i + 1],
            )
        self._atualizar_galeria()

    def remover_selecionado(self):
        if not self.selecionados:
            messagebox.showinfo("Aviso", "Selecione ao menos um cartão para remover.")
            return
        self.lista_imagens = [c for c in self.lista_imagens if c not in self.selecionados]
        self.selecionados.clear()
        self._atualizar_galeria()
        self._atualizar_status()

    def remover_todos(self):
        if not self.lista_imagens:
            return
        if not messagebox.askyesno(
            "Confirmar remoção",
            f"Remover todas as {len(self.lista_imagens)} imagens carregadas?\n"
            "Esta ação não pode ser desfeita.",
            parent=self,
        ):
            return
        self.lista_imagens.clear()
        self.selecionados.clear()
        self._atualizar_galeria()
        self._atualizar_status()

    # ------------------------------------------------------------------
    # Galeria de cartões (miniatura + número + nome do arquivo)
    # ------------------------------------------------------------------
    def _gerar_thumbnail(self, caminho: str):
        """
        Abre a imagem, corrige orientação EXIF (fotos de celular) e gera uma
        miniatura que sempre ocupa a MESMA área quadrada (TAMANHO_THUMB x
        TAMANHO_THUMB), independente da proporção original da imagem. Uma
        imagem retrato e uma paisagem ficam do mesmo tamanho no cartão -
        a imagem é ajustada dentro do quadro (sem cortar nem distorcer),
        com uma leve margem preenchendo o espaço restante.
        A imagem original é fechada/descartada logo em seguida - só a
        miniatura pequena permanece em memória.
        """
        with Image.open(caminho) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGBA")
            reduzida = img.copy()
            reduzida.thumbnail((TAMANHO_THUMB, TAMANHO_THUMB))

            cor_fundo = COR_LETTERBOX[1] if ctk.get_appearance_mode() == "Dark" else COR_LETTERBOX[0]
            moldura = Image.new("RGBA", (TAMANHO_THUMB, TAMANHO_THUMB), cor_fundo)
            pos_x = (TAMANHO_THUMB - reduzida.width) // 2
            pos_y = (TAMANHO_THUMB - reduzida.height) // 2
            moldura.paste(reduzida, (pos_x, pos_y), reduzida)

        return ctk.CTkImage(light_image=moldura, dark_image=moldura, size=(TAMANHO_THUMB, TAMANHO_THUMB))

    def _obter_thumbnail_cacheada(self, caminho: str):
        if caminho not in self.cache_thumbnails:
            try:
                self.cache_thumbnails[caminho] = self._gerar_thumbnail(caminho)
            except Exception:
                self.cache_thumbnails[caminho] = None  # imagem corrompida/ilegível
        return self.cache_thumbnails[caminho]

    def _atualizar_galeria(self):
        """
        Sincroniza a grade de cartões com self.lista_imagens SEM destruir e
        recriar os cartões que já existem - eles só são reposicionados, com
        o número de ordem e a borda de seleção atualizados. Isso evita o
        "piscar" da galeria inteira: um cartão só é de fato criado quando a
        imagem é adicionada, e só é destruído quando ela é removida.
        """
        caminhos_atuais = set(self.lista_imagens)

        # Remove cartões de imagens que não estão mais na lista
        for caminho in list(self._cartoes.keys()):
            if caminho not in caminhos_atuais:
                self._cartoes[caminho]["frame"].destroy()
                del self._cartoes[caminho]

        # Cria os cartões novos e reposiciona todos (novos e existentes)
        for indice, caminho in enumerate(self.lista_imagens):
            if caminho not in self._cartoes:
                self._cartoes[caminho] = self._criar_cartao(caminho)
            self._posicionar_cartao(caminho, indice)

        self._atualizar_status()

    def _criar_cartao(self, caminho: str):
        """Cria (sem posicionar ainda) os widgets de um cartão para a imagem."""
        cartao = ctk.CTkFrame(
            self.galeria,
            width=LARGURA_CARTAO,
            height=TAMANHO_THUMB + 60,
            corner_radius=10,
            border_width=3,
            border_color=COR_BORDA_NORMAL,
        )
        cartao.grid_propagate(False)

        # Número de ordem (badge no canto superior esquerdo do cartão)
        badge = ctk.CTkLabel(
            cartao,
            text="00",
            width=26,
            height=20,
            corner_radius=6,
            fg_color=COR_BORDA_SELECIONADA,
            text_color="white",
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        badge.place(x=6, y=6)

        # Miniatura da imagem (tamanho padronizado - ver _gerar_thumbnail)
        thumb = self._obter_thumbnail_cacheada(caminho)
        rotulo_imagem = ctk.CTkLabel(
            cartao, text="" if thumb else "⚠️ Erro ao ler imagem", image=thumb, width=TAMANHO_THUMB
        )
        rotulo_imagem.pack(pady=(30, 4))

        # Nome do arquivo (apenas na interface - NÃO aparece no PDF gerado)
        rotulo_nome = ctk.CTkLabel(
            cartao,
            text=truncar_nome(os.path.basename(caminho)),
            font=ctk.CTkFont(size=10),
            text_color="gray70",
        )
        rotulo_nome.pack(pady=(0, 6))

        # Registra os widgets do cartão para seleção/arraste/rolagem
        for widget in (cartao, badge, rotulo_imagem, rotulo_nome):
            self._widget_para_caminho[widget] = caminho
            widget.bind("<ButtonPress-1>", self._ao_pressionar_cartao)
            widget.bind("<B1-Motion>", self._ao_arrastar_cartao)
            widget.bind("<ButtonRelease-1>", self._ao_soltar_cartao)
            # Garante que o scroll do mouse funcione mesmo com o cursor em
            # cima de um cartão (ver _rolar_galeria).
            widget.bind("<MouseWheel>", self._rolar_galeria)
            widget.bind("<Button-4>", self._rolar_galeria)
            widget.bind("<Button-5>", self._rolar_galeria)

        return {"frame": cartao, "badge": badge}

    def _posicionar_cartao(self, caminho: str, indice: int):
        """Coloca um cartão já existente na célula certa da grade e atualiza
        seu número de ordem e destaque de seleção - sem recriar nada."""
        info = self._cartoes[caminho]
        linha, coluna = divmod(indice, COLUNAS_GALERIA)
        info["frame"].grid(row=linha, column=coluna, padx=6, pady=6, sticky="n")
        info["badge"].configure(text=f"{indice + 1:02d}")
        selecionado = caminho in self.selecionados
        info["frame"].configure(
            border_color=COR_BORDA_SELECIONADA if selecionado else COR_BORDA_NORMAL
        )

    def _atualizar_selecao_visual(self):
        """
        Atualiza apenas a borda dos cartões conforme a seleção atual - usado
        quando SÓ a seleção mudou (clique simples/Ctrl/Shift), sem qualquer
        alteração de ordem. É uma operação leve (não mexe em posição, número
        nem miniatura), então não causa nenhum "piscar" visual.
        """
        for caminho, info in self._cartoes.items():
            selecionado = caminho in self.selecionados
            info["frame"].configure(
                border_color=COR_BORDA_SELECIONADA if selecionado else COR_BORDA_NORMAL
            )
        self._atualizar_status()

    # ------------------------------------------------------------------
    # Rolagem do mouse dentro da galeria
    # ------------------------------------------------------------------
    def _rolar_galeria(self, event):
        """
        Encaminha a rolagem do mouse para a área de rolagem da galeria,
        mesmo quando o cursor está sobre um cartão. O CustomTkinter tenta
        detectar isso automaticamente, mas widgets com bindings próprios de
        clique (como os nossos cartões) podem atrapalhar essa detecção -
        por isso rolamos explicitamente aqui.
        """
        canvas_da_galeria = self.galeria._parent_canvas
        topo, base = canvas_da_galeria.yview()
        if topo <= 0.0 and base >= 1.0:
            return "break"  # conteúdo cabe inteiro na tela, nada para rolar

        if event.num == 5 or getattr(event, "delta", 0) < 0:
            canvas_da_galeria.yview_scroll(2, "units")
        elif event.num == 4 or getattr(event, "delta", 0) > 0:
            canvas_da_galeria.yview_scroll(-2, "units")
        return "break"

    # ------------------------------------------------------------------
    # Seleção (clique simples / Ctrl+clique / Shift+clique) e arraste
    # (mover o cartão para reordenar) - tudo feito com os mesmos 3 eventos
    # de mouse para diferenciar "clicar para selecionar" de "arrastar".
    # ------------------------------------------------------------------
    def _caminho_do_widget(self, widget):
        # IMPORTANTE: o CustomTkinter desenha cada widget usando um
        # Canvas/Label INTERNO que fica por cima do widget que criamos, e é
        # esse widget interno que efetivamente recebe o evento de clique
        # (event.widget). Por isso subimos pela cadeia de ".master" até
        # encontrar um widget conhecido, em vez de comparar event.widget
        # diretamente com o dicionário.
        while widget is not None:
            if widget in self._widget_para_caminho:
                return self._widget_para_caminho[widget]
            widget = widget.master if hasattr(widget, "master") else None
        return None

    def _ao_pressionar_cartao(self, event):
        caminho = self._caminho_do_widget(event.widget)
        if caminho is None:
            return
        self._arrastando_caminho = caminho
        self._arraste_em_progresso = False
        self._pos_inicial_mouse = (event.x_root, event.y_root)

    def _ao_arrastar_cartao(self, event):
        if self._arrastando_caminho is None:
            return
        dx = event.x_root - self._pos_inicial_mouse[0]
        dy = event.y_root - self._pos_inicial_mouse[1]
        if not self._arraste_em_progresso and (abs(dx) > 8 or abs(dy) > 8):
            self._arraste_em_progresso = True

        if not self._arraste_em_progresso:
            return

        widget_alvo = self.winfo_containing(event.x_root, event.y_root)
        caminho_alvo = self._caminho_do_widget(widget_alvo)
        if caminho_alvo is not None and caminho_alvo != self._arrastando_caminho:
            idx_origem = self.lista_imagens.index(self._arrastando_caminho)
            idx_destino = self.lista_imagens.index(caminho_alvo)
            item = self.lista_imagens.pop(idx_origem)
            self.lista_imagens.insert(idx_destino, item)
            self.selecionados = {self._arrastando_caminho}
            self._atualizar_galeria()

    def _ao_soltar_cartao(self, event):
        if self._arrastando_caminho is None:
            return
        if not self._arraste_em_progresso:
            # Foi um clique simples (sem arrastar) -> tratar seleção.
            # Como só a borda dos cartões muda aqui, usamos a atualização
            # "leve" (_atualizar_selecao_visual), sem recriar/reposicionar
            # nada - a galeria toda não pisca mais a cada clique.
            caminho = self._arrastando_caminho
            ctrl_pressionado = bool(event.state & 0x0004)
            shift_pressionado = bool(event.state & 0x0001)

            if shift_pressionado and self._caminho_ultimo_click is not None:
                idx_a = self.lista_imagens.index(self._caminho_ultimo_click)
                idx_b = self.lista_imagens.index(caminho)
                inicio, fim = sorted((idx_a, idx_b))
                self.selecionados = set(self.lista_imagens[inicio:fim + 1])
            elif ctrl_pressionado:
                if caminho in self.selecionados:
                    self.selecionados.discard(caminho)
                else:
                    self.selecionados.add(caminho)
            else:
                self.selecionados = {caminho}

            self._caminho_ultimo_click = caminho
            self._atualizar_selecao_visual()

        self._arrastando_caminho = None
        self._arraste_em_progresso = False

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def _atualizar_status(self, mensagem=None):
        total = len(self.lista_imagens)
        if mensagem:
            self.label_status.configure(text=mensagem)
            return

        if total == 0:
            texto = "Nenhuma imagem carregada."
        else:
            texto = texto_no_plural(total, "imagem carregada", "imagens carregadas") + "."

        selecionadas = len(self.selecionados)
        if selecionadas:
            texto += "  (" + texto_no_plural(selecionadas, "selecionada", "selecionadas") + ")"

        self.label_status.configure(text=texto)

    # ------------------------------------------------------------------
    # Geração do PDF
    # ------------------------------------------------------------------
    def iniciar_geracao_pdf(self):
        if not self.lista_imagens:
            messagebox.showwarning("Aviso", "Adicione ao menos uma imagem antes de gerar o PDF.")
            return

        caminho_saida = filedialog.asksaveasfilename(
            title="Salvar ECT como...",
            defaultextension=".pdf",
            filetypes=[("Arquivo PDF", "*.pdf")],
            initialfile=self._sugerir_nome_arquivo(),
            parent=self,
        )
        if not caminho_saida:
            return

        # Desabilita o botão e roda a geração em uma thread separada
        # para a interface não travar durante o processamento das imagens.
        self.botao_gerar.configure(state="disabled", text="Gerando...")
        thread = threading.Thread(
            target=self._gerar_pdf_worker, args=(caminho_saida,), daemon=True
        )
        thread.start()

    def _sugerir_nome_arquivo(self):
        titulo = self.entry_titulo.get().strip()
        if titulo:
            nome_limpo = re.sub(r"[^\w\-. ]", "_", titulo)[:60]
            return f"ECT_{nome_limpo}.pdf"
        return f"ECT_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

    def _gerar_pdf_worker(self, caminho_saida):
        """
        Executa em thread separada. Processa UMA imagem por vez (abre,
        redimensiona, desenha na página, fecha) para manter o consumo de
        memória baixo mesmo com muitas imagens de alta resolução.

        Observação: o nome original do arquivo NUNCA é impresso no PDF -
        apenas a numeração da evidência (ex: "Evidência 1 de 5"), pois
        nomes de screenshot costumam ser genéricos e sem valor informativo
        para quem revisa o documento.
        """
        try:
            largura_pagina, altura_pagina = A4
            margem = 15 * mm
            titulo = self.entry_titulo.get().strip()

            c = canvas.Canvas(caminho_saida, pagesize=A4)
            total = len(self.lista_imagens)

            for indice, caminho_imagem in enumerate(self.lista_imagens, start=1):
                self._atualizar_progresso(indice / total, f"Processando {indice}/{total}...")

                # --- Cabeçalho da página ---
                y_cursor = altura_pagina - margem
                c.setFont("Helvetica-Bold", 12)
                if titulo:
                    c.drawString(margem, y_cursor, titulo)
                    y_cursor -= 16

                c.setFont("Helvetica", 9)
                c.setFillGray(0.4)
                c.drawString(margem, y_cursor, f"Evidência {indice} de {total}")
                c.setFillGray(0)
                y_cursor -= 10  # espaço antes da imagem

                # --- Área disponível para a imagem ---
                altura_disponivel = y_cursor - margem  # respeita rodapé
                largura_disponivel = largura_pagina - (2 * margem)

                # Abre a imagem, calcula o tamanho e desenha - fecha em seguida
                with Image.open(caminho_imagem) as img:
                    img = ImageOps.exif_transpose(img)
                    img = img.convert("RGB")  # normaliza modo de cor (evita erros com PNG RGBA/CMYK)
                    largura_img, altura_img = img.size
                    largura_final, altura_final = calcular_dimensoes_ajustadas(
                        largura_img, altura_img, largura_disponivel, altura_disponivel
                    )
                    x_imagem = margem + (largura_disponivel - largura_final) / 2
                    y_imagem = margem + (altura_disponivel - altura_final) / 2

                    c.drawImage(
                        ImageReader(img),
                        x_imagem,
                        y_imagem,
                        width=largura_final,
                        height=altura_final,
                        preserveAspectRatio=True,
                        anchor="c",
                    )

                # --- Rodapé ---
                c.setFont("Helvetica", 8)
                c.setFillGray(0.5)
                c.drawCentredString(largura_pagina / 2, margem / 2, f"Página {indice} de {total}")
                c.setFillGray(0)

                c.showPage()

            c.save()
            self._atualizar_progresso(1.0, "Concluído!")
            self.after(0, lambda: self._finalizar_geracao(sucesso=True, caminho=caminho_saida))

        except Exception as erro:
            traceback.print_exc()
            self.after(0, lambda: self._finalizar_geracao(sucesso=False, erro=str(erro)))

    def _atualizar_progresso(self, fracao, texto):
        self.after(0, lambda: self.progress_bar.set(fracao))
        self.after(0, lambda: self.label_status.configure(text=texto))

    def _finalizar_geracao(self, sucesso, caminho=None, erro=None):
        self.botao_gerar.configure(state="normal", text="📄  Gerar ECT (PDF)")
        if sucesso:
            self.label_status.configure(text=f"PDF gerado com sucesso: {caminho}")
            messagebox.showinfo("Sucesso", f"ECT gerado com sucesso em:\n{caminho}")
        else:
            self.label_status.configure(text="Erro ao gerar o PDF.")
            messagebox.showerror("Erro", f"Ocorreu um erro ao gerar o PDF:\n{erro}")
            self.progress_bar.set(0)


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------
def main():
    app = GeradorECTApp()
    app.mainloop()


if __name__ == "__main__":
    main()
