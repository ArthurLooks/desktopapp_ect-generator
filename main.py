import json
import os
import re
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageOps

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader

import icones

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


# ---------------------------------------------------------------------------
# Constantes de configuração
# ---------------------------------------------------------------------------
NOME_APP = "Gerador de PDF"
PREFIXO_ARQUIVO_SUGERIDO = "PDF"

EXTENSOES_VALIDAS = (".png", ".jpg", ".jpeg", ".bmp", ".gif")

TAMANHO_THUMB = 150          # tamanho FIXO (px) da área de miniatura em todo cartão
COLUNAS_GALERIA = 4          # número fixo de colunas na grade de cartões
LARGURA_CARTAO = 168         # largura de cada cartão (px), incluindo espaçamento
COR_LETTERBOX = ("#dbdbdb", "#2b2b2b")  # fundo (claro, escuro) da moldura da miniatura
COR_BORDA_NORMAL = "gray30"
COR_BORDA_SELECIONADA = "#3B8ED0"
COR_ICONE = "#FFFFFF"
NOME_ARQUIVO_ICONE = "favicon.ico"  # precisa estar na mesma pasta do script/exe

LIMITE_CAMINHO_ARQUIVO = 260  # limite prático e conservador para o caminho completo do arquivo
DPI_IMPRESSAO = 150  # resolução suficiente para leitura em tela/impressão em A4
MAX_WORKERS_IO = 4   # threads paralelas para ler/redimensionar imagens

# Configuração visual básica (leve, sem dependências pesadas)
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


# ---------------------------------------------------------------------------
# Funções utilitárias (puras, sem dependência de estado da UI)
# ---------------------------------------------------------------------------

def natural_sort_key(caminho_arquivo: str):
    """
    Gera uma chave de ordenação 'natural' baseada no nome do arquivo.
    Isso garante que 'imagem2.png' venha antes de 'imagem10.png'
    (diferente da ordenação alfabética padrão, que colocaria 10 antes de 2).
    """
    nome = os.path.basename(caminho_arquivo)
    partes = re.split(r"(\d+)", nome)
    chave = [int(parte) if parte.isdigit() else parte.lower() for parte in partes]
    return chave


def sort_key_data_criacao(caminho_arquivo: str):
    """Chave de ordenação baseada na data de criação/modificação do arquivo."""
    try:
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


def caminho_do_recurso(nome_arquivo: str):
    """
    Resolve o caminho de um arquivo auxiliar (como o ícone) tanto quando o
    app roda via 'python main.py' quanto quando roda como .exe empacotado
    pelo PyInstaller (--onefile extrai os arquivos embutidos para uma pasta
    temporária apontada por sys._MEIPASS).
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, nome_arquivo)


def caminho_excede_limite(caminho: str, limite: int = LIMITE_CAMINHO_ARQUIVO) -> bool:
    """
    Verifica se o caminho ABSOLUTO do arquivo passa de um limite prático de
    comprimento. Sistemas de arquivo e programas variam no que aceitam, mas
    caminhos muito longos costumam falhar ao serem abertos (silenciosamente
    ou com erro) independente do sistema operacional - por isso filtramos e
    avisamos antes de tentar processar o arquivo.
    """
    return len(os.path.abspath(caminho)) >= limite


# ---------------------------------------------------------------------------
# Persistência de configuração (capa personalizada) entre sessões do app
# ---------------------------------------------------------------------------

def obter_pasta_config() -> str:
    """
    Pasta gravável para guardar preferências do usuário (capa personalizada).
    Usa %APPDATA% no Windows (padrão para dados de aplicativo por usuário) e
    a pasta pessoal em outros sistemas, nunca a pasta do próprio .exe, que
    pode estar em um local somente leitura (ex: pasta compartilhada em rede).
    """
    base = os.getenv("APPDATA") or os.path.expanduser("~")
    pasta = os.path.join(base, ".gerador-pdf")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def caminho_config_capa() -> str:
    return os.path.join(obter_pasta_config(), "config_capa.json")


def caminho_imagem_capa() -> str:
    return os.path.join(obter_pasta_config(), "imagem_capa.png")


def carregar_config_capa() -> dict:
    padrao = {"usar_capa": False, "tem_imagem": False}
    try:
        with open(caminho_config_capa(), "r", encoding="utf-8") as f:
            dados = json.load(f)
        padrao.update(dados)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return padrao


def salvar_config_capa(config: dict):
    with open(caminho_config_capa(), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Classe principal da aplicação
# ---------------------------------------------------------------------------

if DND_AVAILABLE:
    class JanelaBase(TkinterDnD.DnDWrapper, ctk.CTk):
        def __init__(self):
            super().__init__()
            self.TkdndVersion = TkinterDnD._require(self)
else:
    class JanelaBase(ctk.CTk):
        pass


class GeradorPDFApp(JanelaBase):
    def __init__(self):
        super().__init__()

        self.title(NOME_APP)
        self.geometry("920x680")
        self.minsize(820, 560)

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
        self._cartoes = {}

        # Estado de seleção/arraste da galeria (seleção guardada pelo
        # CAMINHO do arquivo, não pelo índice - continua acompanhando a
        # imagem certa mesmo depois de reordenar a lista).
        self.selecionados = set()
        self._widget_para_caminho = {}
        self._caminho_ultimo_click = None
        self._arrastando_caminho = None
        self._arraste_em_progresso = False
        self._pos_inicial_mouse = (0, 0)

        # Configuração de capa personalizada, carregada do disco (persiste
        # entre sessões do app).
        self.config_capa = carregar_config_capa()

        # Ícones pré-renderizados (mesma biblioteca/tamanho para todos)
        self._preparar_icones()

        self._montar_interface()

    # ------------------------------------------------------------------
    # Ícones
    # ------------------------------------------------------------------
    def _preparar_icones(self):
        self.icones = {
            "pasta": ctk.CTkImage(icones.icone_pasta(cor=COR_ICONE), size=(18, 18)),
            "imagem": ctk.CTkImage(icones.icone_imagem(cor=COR_ICONE), size=(18, 18)),
            "ordenar_nome": ctk.CTkImage(icones.icone_ordenar_nome(cor=COR_ICONE), size=(18, 18)),
            "ordenar_data": ctk.CTkImage(icones.icone_ordenar_data(cor=COR_ICONE), size=(18, 18)),
            "seta_esquerda": ctk.CTkImage(icones.icone_seta("esquerda", cor=COR_ICONE), size=(18, 18)),
            "seta_direita": ctk.CTkImage(icones.icone_seta("direita", cor=COR_ICONE), size=(18, 18)),
            "lixeira": ctk.CTkImage(icones.icone_lixeira(cor=COR_ICONE), size=(18, 18)),
            "lixeira_tudo": ctk.CTkImage(icones.icone_lixeira(cor=COR_ICONE, com_x=True), size=(18, 18)),
            "documento": ctk.CTkImage(icones.icone_documento(cor=COR_ICONE), size=(18, 18)),
            "download": ctk.CTkImage(icones.icone_download(cor=COR_ICONE), size=(20, 20)),
        }

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
            frame, text="Título do Documento:", font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, padx=(12, 8), pady=(12, 4), sticky="w")

        self.entry_titulo = ctk.CTkEntry(
            frame, placeholder_text="Ex: TC-1234 - Login com usuário válido, ou o nome do seu relatório"
        )
        self.entry_titulo.grid(row=0, column=1, padx=(0, 12), pady=(12, 4), sticky="ew")

        self.botao_capa = ctk.CTkButton(
            frame,
            text="Configurar Capa",
            image=self.icones["documento"],
            compound="left",
            anchor="w",
            command=self.abrir_configuracao_capa,
            width=180,
            height=30,
            cursor="hand2",
            fg_color="transparent",
            border_width=1,
        )
        self.botao_capa.grid(row=1, column=0, padx=(12, 8), pady=(2, 12), sticky="w")

        self.label_status_capa = ctk.CTkLabel(frame, text="", text_color="gray", anchor="w")
        self.label_status_capa.grid(row=1, column=1, padx=(0, 12), pady=(2, 12), sticky="w")
        self._atualizar_label_capa()

    def _montar_botoes_topo(self):
        """
        Barra de ferramentas em DUAS linhas para garantir que nenhum texto de
        botão seja cortado, independentemente do tamanho da janela. Todos os
        botões usam a mesma biblioteca de ícones (à esquerda, texto alinhado
        à esquerda ao lado) e cursor de "mão" (pointer) ao passar o mouse.
        """
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(4, 0))

        linha1 = ctk.CTkFrame(frame, fg_color="transparent")
        linha1.pack(fill="x", pady=(0, 4))
        linha2 = ctk.CTkFrame(frame, fg_color="transparent")
        linha2.pack(fill="x")

        botoes_linha1 = [
            ("Selecionar Pasta", "pasta", self.selecionar_pasta),
            ("Adicionar Arquivos", "imagem", self.adicionar_arquivos),
            ("Ordenar por Nome", "ordenar_nome", lambda: self.ordenar_automaticamente("nome")),
            ("Ordenar por Data", "ordenar_data", lambda: self.ordenar_automaticamente("data")),
        ]
        # "Mover Antes/Depois" substitui o antigo "Mover Cima/Baixo": numa
        # galeria em grade (várias colunas), "cima/baixo" não descreve bem
        # o movimento real do cartão. "Antes/Depois" fala da ORDEM da
        # imagem na sequência final do PDF, que é o que importa aqui - a
        # reordenação livre continua disponível arrastando o cartão.
        botoes_linha2 = [
            ("Mover Antes", "seta_esquerda", self.mover_antes),
            ("Mover Depois", "seta_direita", self.mover_depois),
            ("Remover Selecionados", "lixeira", self.remover_selecionado),
            ("Remover Todos", "lixeira_tudo", self.remover_todos),
        ]

        for texto, chave_icone, comando in botoes_linha1:
            ctk.CTkButton(
                linha1, text=texto, image=self.icones[chave_icone], compound="left", anchor="w",
                command=comando, width=205, height=34, cursor="hand2",
            ).pack(side="left", padx=4)
        for texto, chave_icone, comando in botoes_linha2:
            ctk.CTkButton(
                linha2, text=texto, image=self.icones[chave_icone], compound="left", anchor="w",
                command=comando, width=205, height=34, cursor="hand2",
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
        self.galeria = ctk.CTkScrollableFrame(self, label_text="Imagens carregadas")
        self.galeria.grid(row=3, column=0, sticky="nsew", padx=16, pady=8)
        for col in range(COLUNAS_GALERIA):
            self.galeria.grid_columnconfigure(col, weight=1)

        # Área de drop de arquivos externos (Explorer/Finder). Registramos
        # em vários widgets internos da galeria (a área rolável é composta
        # por várias camadas sobrepostas) para garantir que o drop seja
        # capturado não importa onde exatamente o cursor solte o arquivo.
        if DND_AVAILABLE:
            alvos_de_drop = [self, self.galeria]
            canvas_interno = getattr(self.galeria, "_parent_canvas", None)
            if canvas_interno is not None:
                alvos_de_drop.append(canvas_interno)
            for alvo in alvos_de_drop:
                alvo.drop_target_register(DND_FILES)
                alvo.dnd_bind("<<Drop>>", self._ao_soltar_arquivos)

        # Rolagem do mouse em QUALQUER ponto da galeria - não só sobre um
        # cartão. A área rolável é composta por várias camadas internas do
        # CustomTkinter sobrepostas (moldura externa, canvas que hospeda a
        # rolagem, cabeçalho "Imagens carregadas"), então vinculamos o
        # mesmo handler em todas elas para cobrir qualquer espaço vazio
        # entre/abaixo dos cartões.
        widgets_para_rolagem = [self.galeria]
        for atributo in ("_parent_frame", "_parent_canvas", "_label"):
            widget_interno = getattr(self.galeria, atributo, None)
            if widget_interno is not None:
                widgets_para_rolagem.append(widget_interno)
        for widget in widgets_para_rolagem:
            widget.bind("<MouseWheel>", self._rolar_galeria)
            widget.bind("<Button-4>", self._rolar_galeria)
            widget.bind("<Button-5>", self._rolar_galeria)

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
            text="Gerar PDF",
            image=self.icones["download"],
            compound="left",
            anchor="center",
            command=self.iniciar_geracao_pdf,
            height=42,
            font=ctk.CTkFont(size=15, weight="bold"),
            cursor="hand2",
        )
        self.botao_gerar.grid(row=2, column=0, sticky="ew")

    # ------------------------------------------------------------------
    # Configuração de capa personalizada
    # ------------------------------------------------------------------
    def _atualizar_label_capa(self):
        if self.config_capa.get("usar_capa") and self.config_capa.get("tem_imagem"):
            self.label_status_capa.configure(text="✓ Capa ativada")
        elif self.config_capa.get("usar_capa"):
            self.label_status_capa.configure(text="Capa ativada, mas sem imagem selecionada")
        else:
            self.label_status_capa.configure(text="Capa desativada")

    def abrir_configuracao_capa(self):
        JanelaConfigCapa(self)

    # ------------------------------------------------------------------
    # Ações de carregamento de arquivos (sempre via diálogo NATIVO do SO)
    # ------------------------------------------------------------------
    def selecionar_pasta(self):
        pasta = filedialog.askdirectory(title="Selecione a pasta com as imagens", parent=self)
        if not pasta:
            return
        novos = listar_imagens_da_pasta(pasta)
        if not novos:
            messagebox.showinfo("Aviso", "Nenhuma imagem (PNG/JPG) foi encontrada nessa pasta.")
            return
        self._adicionar_arquivos_a_lista(novos)

    def adicionar_arquivos(self):
        arquivos = filedialog.askopenfilenames(
            title="Selecione as imagens",
            filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp *.gif"), ("Todos os arquivos", "*.*")],
            parent=self,
        )
        self._adicionar_arquivos_a_lista(list(arquivos))

    def _ao_soltar_arquivos(self, event):
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

        # Filtra arquivos com caminho longo demais (limite do Windows) antes
        # de tentar processá-los - evita que a leitura quebre mais adiante.
        validos, caminhos_longos = [], []
        for caminho in novos_arquivos:
            if caminho in self.lista_imagens:
                continue
            if caminho_excede_limite(caminho):
                caminhos_longos.append(caminho)
            else:
                validos.append(caminho)

        if caminhos_longos:
            self._avisar_caminhos_longos(caminhos_longos)

        if not validos:
            return

        self.lista_imagens.extend(validos)
        self.lista_imagens.sort(key=natural_sort_key)

        # Gera as miniaturas em segundo plano (thread separada) para a
        # interface não travar mesmo ao adicionar dezenas de imagens de
        # uma vez só - só a criação do CTkImage final acontece de volta na
        # thread principal, que é a única forma segura de mexer na UI.
        self.botao_gerar.configure(state="disabled")
        self._atualizar_status(
            f"Gerando prévias de {texto_no_plural(len(validos), 'imagem', 'imagens')}..."
        )
        thread = threading.Thread(
            target=self._gerar_thumbnails_worker, args=(list(self.lista_imagens),), daemon=True
        )
        thread.start()

    def _avisar_caminhos_longos(self, caminhos_longos):
        exemplos = "\n".join(f"• ...{c[-80:]}" for c in caminhos_longos[:5])
        restante = len(caminhos_longos) - 5
        if restante > 0:
            exemplos += f"\n… e mais {restante} arquivo(s)."
        qtd = len(caminhos_longos)
        frase = "1 arquivo foi ignorado" if qtd == 1 else f"{qtd} arquivos foram ignorados"
        messagebox.showwarning(
            "Caminho de arquivo muito longo",
            f"{frase} "
            f"porque o caminho completo do arquivo é muito longo (mais de {LIMITE_CAMINHO_ARQUIVO} "
            "caracteres), o que impede a leitura em muitos sistemas:\n\n"
            f"{exemplos}\n\n"
            "Solução: mova os arquivos para uma pasta com um caminho mais curto (nomes de pasta "
            "menores ou mais próximos da raiz do disco) e tente novamente.",
            parent=self,
        )

    # ------------------------------------------------------------------
    # Geração de miniaturas em segundo plano
    # ------------------------------------------------------------------
    def _gerar_thumbnails_worker(self, caminhos):
        """
        Roda em thread separada. Usa um pool de threads para ler e
        redimensionar várias imagens em paralelo (a leitura em disco é o
        gargalo, então paralelizar acelera bastante quando há muitos
        arquivos ou quando eles estão numa pasta de rede). Só trabalha com
        Pillow puro aqui - nenhum objeto do Tkinter é tocado fora da
        thread principal, o que evitaria crashes.
        """
        pendentes = [c for c in caminhos if c not in self.cache_thumbnails]
        resultados = {}
        if pendentes:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS_IO) as executor:
                for caminho, imagem_pil in zip(pendentes, executor.map(_preparar_thumbnail_pil, pendentes)):
                    resultados[caminho] = imagem_pil
        self.after(0, lambda: self._aplicar_thumbnails(resultados))

    def _aplicar_thumbnails(self, resultados):
        # Roda de volta na thread principal - aqui sim é seguro criar
        # objetos CTkImage/Tkinter.
        for caminho, imagem_pil in resultados.items():
            if imagem_pil is not None:
                self.cache_thumbnails[caminho] = ctk.CTkImage(
                    light_image=imagem_pil, dark_image=imagem_pil, size=(TAMANHO_THUMB, TAMANHO_THUMB)
                )
            else:
                self.cache_thumbnails[caminho] = None
        self._atualizar_galeria()
        self._atualizar_status()
        self.botao_gerar.configure(state="normal")

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
    # que guarda CAMINHOS de arquivo, não posições).
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
    def _obter_thumbnail_cacheada(self, caminho: str):
        """Fallback síncrono (usado apenas se, por algum motivo, o cache
        ainda não tiver essa miniatura pronta na hora de montar o cartão)."""
        if caminho not in self.cache_thumbnails:
            imagem_pil = _preparar_thumbnail_pil(caminho)
            self.cache_thumbnails[caminho] = (
                ctk.CTkImage(light_image=imagem_pil, dark_image=imagem_pil, size=(TAMANHO_THUMB, TAMANHO_THUMB))
                if imagem_pil is not None
                else None
            )
        return self.cache_thumbnails[caminho]

    def _atualizar_galeria(self):
        """
        Sincroniza a grade de cartões com self.lista_imagens SEM destruir e
        recriar os cartões que já existem - eles só são reposicionados, com
        o número de ordem e a borda de seleção atualizados. Isso evita o
        "piscar" da galeria inteira a cada seleção/reordenação.
        """
        caminhos_atuais = set(self.lista_imagens)

        for caminho in list(self._cartoes.keys()):
            if caminho not in caminhos_atuais:
                self._cartoes[caminho]["frame"].destroy()
                del self._cartoes[caminho]

        for indice, caminho in enumerate(self.lista_imagens):
            if caminho not in self._cartoes:
                self._cartoes[caminho] = self._criar_cartao(caminho)
            self._posicionar_cartao(caminho, indice)

        # Corrige a área de rolagem depois de qualquer alteração na lista:
        # sem isso, ao remover imagens e a galeria encolher, a barra de
        # rolagem podia manter uma posição antiga e "esconder" a primeira
        # fileira mesmo rolando totalmente para cima.
        self._sincronizar_scroll(voltar_ao_topo=True)

        self._atualizar_status()

    def _sincronizar_scroll(self, voltar_ao_topo=False):
        self.galeria.update_idletasks()
        canvas_interno = getattr(self.galeria, "_parent_canvas", None)
        if canvas_interno is None:
            return
        bbox = canvas_interno.bbox("all")
        if bbox:
            canvas_interno.configure(scrollregion=bbox)
        if voltar_ao_topo:
            canvas_interno.yview_moveto(0.0)

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

        thumb = self._obter_thumbnail_cacheada(caminho)
        rotulo_imagem = ctk.CTkLabel(
            cartao, text="" if thumb else "⚠️ Erro ao ler imagem", image=thumb, width=TAMANHO_THUMB
        )
        rotulo_imagem.pack(pady=(30, 4))

        rotulo_nome = ctk.CTkLabel(
            cartao,
            text=truncar_nome(os.path.basename(caminho)),
            font=ctk.CTkFont(size=10),
            text_color="gray70",
        )
        rotulo_nome.pack(pady=(0, 6))

        for widget in (cartao, badge, rotulo_imagem, rotulo_nome):
            self._widget_para_caminho[widget] = caminho
            widget.bind("<ButtonPress-1>", self._ao_pressionar_cartao)
            widget.bind("<B1-Motion>", self._ao_arrastar_cartao)
            widget.bind("<ButtonRelease-1>", self._ao_soltar_cartao)
            widget.bind("<MouseWheel>", self._rolar_galeria)
            widget.bind("<Button-4>", self._rolar_galeria)
            widget.bind("<Button-5>", self._rolar_galeria)

        return {"frame": cartao, "badge": badge}

    def _posicionar_cartao(self, caminho: str, indice: int):
        info = self._cartoes[caminho]
        linha, coluna = divmod(indice, COLUNAS_GALERIA)
        info["frame"].grid(row=linha, column=coluna, padx=6, pady=6, sticky="n")
        info["badge"].configure(text=f"{indice + 1:02d}")
        selecionado = caminho in self.selecionados
        info["frame"].configure(
            border_color=COR_BORDA_SELECIONADA if selecionado else COR_BORDA_NORMAL
        )

    def _atualizar_selecao_visual(self):
        """Atualiza apenas a borda dos cartões conforme a seleção atual -
        usado quando SÓ a seleção mudou, sem alterar ordem/posição."""
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
        canvas_da_galeria = self.galeria._parent_canvas
        topo, base = canvas_da_galeria.yview()
        if topo <= 0.0 and base >= 1.0:
            return "break"
        if event.num == 5 or getattr(event, "delta", 0) < 0:
            canvas_da_galeria.yview_scroll(2, "units")
        elif event.num == 4 or getattr(event, "delta", 0) > 0:
            canvas_da_galeria.yview_scroll(-2, "units")
        return "break"

    # ------------------------------------------------------------------
    # Seleção (clique simples / Ctrl+clique / Shift+clique) e arraste
    # ------------------------------------------------------------------
    def _caminho_do_widget(self, widget):
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
            title="Salvar PDF como...",
            defaultextension=".pdf",
            filetypes=[("Arquivo PDF", "*.pdf")],
            initialfile=self._sugerir_nome_arquivo(),
            parent=self,
        )
        if not caminho_saida:
            return

        self.botao_gerar.configure(state="disabled", text="Gerando...")
        thread = threading.Thread(
            target=self._gerar_pdf_worker, args=(caminho_saida,), daemon=True
        )
        thread.start()

    def _sugerir_nome_arquivo(self):
        titulo = self.entry_titulo.get().strip()
        if titulo:
            nome_limpo = re.sub(r"[^\w\-. ]", "_", titulo)[:60]
            return f"{PREFIXO_ARQUIVO_SUGERIDO}_{nome_limpo}.pdf"
        return f"{PREFIXO_ARQUIVO_SUGERIDO}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

    def _gerar_pdf_worker(self, caminho_saida):
        """
        Executa em thread separada. Usa um pool de threads para preparar
        (ler, corrigir rotação, redimensionar) as imagens em paralelo -
        enquanto uma página está sendo desenhada no PDF, as próximas
        imagens já estão sendo lidas/processadas em segundo plano, o que
        acelera bastante a geração (principalmente com muitas imagens ou
        arquivos em pastas de rede). As imagens também são reduzidas para
        a resolução real necessária na impressão (150 DPI) antes de serem
        embutidas, o que deixa tanto a geração quanto o arquivo final bem
        mais rápidos/leves sem perda perceptível de qualidade.

        Imagens que falharem ao processar (corrompidas, removidas do disco
        etc.) são puladas com um aviso no final, em vez de derrubar a
        geração inteira do PDF.

        Observação: o nome original do arquivo NUNCA é impresso no PDF -
        apenas a numeração da imagem (ex: "Imagem 1 de 5").
        """
        try:
            largura_pagina, altura_pagina = A4
            margem = 15 * mm
            titulo = self.entry_titulo.get().strip()
            usar_capa = self.config_capa.get("usar_capa", False)

            c = canvas.Canvas(caminho_saida, pagesize=A4)

            if usar_capa:
                self._desenhar_capa(c, largura_pagina, altura_pagina)

            total = len(self.lista_imagens)
            largura_disponivel = largura_pagina - (2 * margem)
            altura_disponivel_max = altura_pagina - (2 * margem) - 26  # espaço p/ cabeçalho+rodapé

            erros = []
            args_preparo = [
                (caminho, largura_disponivel, altura_disponivel_max, DPI_IMPRESSAO)
                for caminho in self.lista_imagens
            ]

            with ThreadPoolExecutor(max_workers=MAX_WORKERS_IO) as executor:
                resultados = executor.map(_preparar_imagem_para_pdf, args_preparo)

                for indice, (caminho_imagem, resultado) in enumerate(
                    zip(self.lista_imagens, resultados), start=1
                ):
                    self._atualizar_progresso(indice / total, f"Processando {indice}/{total}...")

                    imagem_pronta, largura_final, altura_final, erro = resultado
                    if erro is not None:
                        erros.append((caminho_imagem, erro))
                        continue

                    y_cursor = altura_pagina - margem
                    c.setFont("Helvetica-Bold", 12)
                    if titulo:
                        c.drawString(margem, y_cursor, titulo)
                        y_cursor -= 16

                    c.setFont("Helvetica", 9)
                    c.setFillGray(0.4)
                    c.drawString(margem, y_cursor, f"Imagem {indice} de {total}")
                    c.setFillGray(0)
                    y_cursor -= 10

                    altura_disponivel = y_cursor - margem
                    x_imagem = margem + (largura_disponivel - largura_final) / 2
                    y_imagem = margem + (altura_disponivel - altura_final) / 2

                    c.drawImage(
                        ImageReader(imagem_pronta),
                        x_imagem,
                        y_imagem,
                        width=largura_final,
                        height=altura_final,
                        preserveAspectRatio=True,
                        anchor="c",
                    )

                    c.setFont("Helvetica", 8)
                    c.setFillGray(0.5)
                    c.drawCentredString(largura_pagina / 2, margem / 2, f"Página {indice} de {total}")
                    c.setFillGray(0)

                    c.showPage()

            c.save()
            self._atualizar_progresso(1.0, "Concluído!")
            self.after(0, lambda: self._finalizar_geracao(sucesso=True, caminho=caminho_saida, erros=erros))

        except Exception as erro:
            traceback.print_exc()
            self.after(0, lambda: self._finalizar_geracao(sucesso=False, erro=str(erro)))

    def _desenhar_capa(self, c, largura_pagina, altura_pagina):
        """
        Desenha a página de capa: a imagem escolhida pelo usuário, ajustada
        para caber na página inteira (com uma margem), sem cortar nem
        distorcer. Não entra na numeração 'Imagem X de Y' das páginas
        seguintes. Se a imagem configurada não existir mais no disco por
        algum motivo, a capa é simplesmente pulada (sem quebrar o PDF).
        """
        if not self.config_capa.get("tem_imagem"):
            return
        caminho_imagem = caminho_imagem_capa()
        if not os.path.exists(caminho_imagem):
            return
        try:
            margem = 20 * mm
            largura_disponivel = largura_pagina - (2 * margem)
            altura_disponivel = altura_pagina - (2 * margem)
            with Image.open(caminho_imagem) as img:
                img = img.convert("RGB")
                largura_final, altura_final = calcular_dimensoes_ajustadas(
                    img.width, img.height, largura_disponivel, altura_disponivel
                )
                x = margem + (largura_disponivel - largura_final) / 2
                y = margem + (altura_disponivel - altura_final) / 2
                c.drawImage(
                    ImageReader(img), x, y,
                    width=largura_final, height=altura_final,
                    preserveAspectRatio=True, anchor="c",
                )
            c.showPage()
        except Exception:
            pass  # capa é um extra opcional - nunca deve derrubar o PDF inteiro

    def _atualizar_progresso(self, fracao, texto):
        self.after(0, lambda: self.progress_bar.set(fracao))
        self.after(0, lambda: self.label_status.configure(text=texto))

    def _finalizar_geracao(self, sucesso, caminho=None, erro=None, erros=None):
        self.botao_gerar.configure(state="normal", text="Gerar PDF")
        if sucesso:
            self.label_status.configure(text=f"PDF gerado com sucesso: {caminho}")
            mensagem = f"PDF gerado com sucesso em:\n{caminho}"
            if erros:
                exemplos = "\n".join(f"• {os.path.basename(c)} ({e})" for c, e in erros[:5])
                if len(erros) == 1:
                    frase = "1 imagem foi ignorada por erro de leitura e não entrou no PDF"
                else:
                    frase = f"{len(erros)} imagens foram ignoradas por erro de leitura e não entraram no PDF"
                mensagem += f"\n\n⚠️ {frase}:\n{exemplos}"
            messagebox.showinfo("Sucesso", mensagem)
        else:
            self.label_status.configure(text="Erro ao gerar o PDF.")
            messagebox.showerror("Erro", f"Ocorreu um erro ao gerar o PDF:\n{erro}")
            self.progress_bar.set(0)


# ---------------------------------------------------------------------------
# Preparação de imagens (funções livres, seguras para rodar em threads -
# não tocam em nenhum objeto do Tkinter)
# ---------------------------------------------------------------------------

def _preparar_thumbnail_pil(caminho: str):
    """
    Abre a imagem, corrige orientação EXIF e gera uma miniatura que sempre
    ocupa a MESMA área quadrada (TAMANHO_THUMB x TAMANHO_THUMB), com uma
    margem preenchendo o espaço restante. Retorna None em caso de erro
    (arquivo corrompido, caminho inválido etc.) - quem chama decide como
    exibir isso ao usuário.
    """
    try:
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
            return moldura
    except Exception:
        return None


def _preparar_imagem_para_pdf(args):
    """
    Abre, corrige rotação e redimensiona uma imagem para o tamanho exato
    que ela vai ocupar no PDF (na resolução de impressão definida por
    DPI_IMPRESSAO, nunca maior que isso) - reduz o trabalho de compressão
    do ReportLab e o tamanho final do arquivo. Roda em thread separada via
    ThreadPoolExecutor; nunca levanta exceção (devolve o erro como string
    para quem chama decidir o que fazer), o que permite processar o resto
    das imagens mesmo se uma falhar.
    """
    caminho, largura_max_pt, altura_max_pt, dpi = args
    try:
        with Image.open(caminho) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            largura_final_pt, altura_final_pt = calcular_dimensoes_ajustadas(
                img.width, img.height, largura_max_pt, altura_max_pt
            )
            largura_px_alvo = max(1, int(largura_final_pt / 72 * dpi))
            altura_px_alvo = max(1, int(altura_final_pt / 72 * dpi))
            if img.width > largura_px_alvo and img.height > altura_px_alvo:
                img = img.resize((largura_px_alvo, altura_px_alvo), Image.LANCZOS)
            copia = img.copy()
        return (copia, largura_final_pt, altura_final_pt, None)
    except Exception as erro:
        return (None, 0, 0, str(erro))


# ---------------------------------------------------------------------------
# Janela de configuração da capa personalizada
# ---------------------------------------------------------------------------

class JanelaConfigCapa(ctk.CTkToplevel):
    def __init__(self, app: GeradorPDFApp):
        super().__init__(app)
        self.app = app
        self.title("Configurar Capa")

        # Caminho de uma imagem recém-selecionada nesta sessão do diálogo
        # (só é copiada para a pasta de configuração se o usuário salvar).
        # "REMOVER" é um valor sentinela para indicar remoção explícita.
        self._nova_imagem_path = None

        self._montar()
        self._carregar_valores_atuais()

        # IMPORTANTE: o tamanho da janela é calculado a partir do conteúdo
        # real (winfo_reqwidth/reqheight) em vez de um valor fixo "chutado".
        # Um valor fixo pode cortar os botões de baixo em sistemas com
        # fontes/DPI diferentes do que foi usado para calibrar o tamanho -
        # calcular dinamicamente evita esse problema em qualquer máquina.
        self.update_idletasks()
        largura = self.winfo_reqwidth()
        altura = self.winfo_reqheight() + 16  # pequena folga de segurança

        # A POSIÇÃO também é definida explicitamente (centralizada sobre a
        # janela principal). Deixar sem posição no geometry() faz o próprio
        # gerenciador de janelas do sistema operacional decidir onde colocar
        # a janela - e em vários deles isso causa o efeito de abrir num
        # lugar (ex: centralizado, por acaso) e "pular" para outro (em geral
        # o canto superior esquerdo) assim que qualquer novo evento de
        # geometria dispara. Calculando e fixando +x+y nós mesmos, a posição
        # fica estável e previsível em qualquer sistema.
        pos_x = app.winfo_x() + (app.winfo_width() - largura) // 2
        pos_y = app.winfo_y() + (app.winfo_height() - altura) // 2
        self.geometry(f"{largura}x{altura}+{max(pos_x, 0)}+{max(pos_y, 0)}")
        self.minsize(largura, altura)
        self.resizable(False, False)

        # grab_set() só funciona depois que a janela já está "viewable"
        # (efetivamente desenhada na tela pelo gerenciador de janelas).
        # Chamar antes disso derruba o app em alguns sistemas (principalmente
        # Linux) com "grab failed: window not viewable". update_idletasks()
        # + wait_visibility() garantem que a janela já apareceu antes de
        # tentar capturar o foco exclusivo; o try/except é uma rede de
        # segurança para ambientes onde isso ainda assim falhe (a janela
        # continua funcionando, só sem bloquear o app por trás - não é
        # ideal, mas nunca deve travar o programa).
        self.transient(app)
        self.deiconify()
        self.lift()
        self.focus_force()
        try:
            self.wait_visibility()
            self.grab_set()
        except Exception:
            pass

    def _montar(self):
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="Capa do PDF", font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, padx=20, pady=(20, 4), sticky="w")
        ctk.CTkLabel(
            self,
            text="Selecione uma imagem para usar como capa (primeira página) do\n"
                 "PDF. Fica salva no seu usuário e é reaproveitada da próxima vez\n"
                 "que você abrir o aplicativo.",
            text_color="gray", justify="left",
        ).grid(row=1, column=0, padx=20, pady=(0, 16), sticky="w")

        self.chk_usar_capa = ctk.CTkCheckBox(self, text="Incluir esta capa ao gerar o PDF")
        self.chk_usar_capa.grid(row=2, column=0, padx=20, pady=(0, 16), sticky="w")

        self.preview_imagem = ctk.CTkLabel(
            self, text="Nenhuma imagem selecionada", width=260, height=180,
            fg_color=("#dbdbdb", "#2b2b2b"), corner_radius=8,
        )
        self.preview_imagem.grid(row=3, column=0, padx=20, pady=(0, 16))

        frame_botoes_imagem = ctk.CTkFrame(self, fg_color="transparent")
        frame_botoes_imagem.grid(row=4, column=0, padx=20, pady=(0, 12), sticky="ew")
        frame_botoes_imagem.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            frame_botoes_imagem, text="Selecionar Imagem", command=self._selecionar_imagem,
            cursor="hand2", height=32, image=self.app.icones["imagem"], compound="left", anchor="w",
        ).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        ctk.CTkButton(
            frame_botoes_imagem, text="Remover", command=self._remover_imagem,
            cursor="hand2", height=32, image=self.app.icones["lixeira"], compound="left", anchor="w",
        ).grid(row=0, column=1, padx=(6, 0), sticky="ew")

        frame_botoes = ctk.CTkFrame(self, fg_color="transparent")
        frame_botoes.grid(row=5, column=0, padx=20, pady=(8, 20), sticky="ew")
        frame_botoes.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            frame_botoes, text="Cancelar", command=self.destroy, cursor="hand2",
            fg_color="transparent", border_width=1,
        ).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        ctk.CTkButton(
            frame_botoes, text="Salvar", command=self._salvar, cursor="hand2",
        ).grid(row=0, column=1, padx=(6, 0), sticky="ew")

    def _carregar_valores_atuais(self):
        config = self.app.config_capa
        if config.get("usar_capa"):
            self.chk_usar_capa.select()
        if config.get("tem_imagem") and os.path.exists(caminho_imagem_capa()):
            self._mostrar_preview(caminho_imagem_capa())

    def _selecionar_imagem(self):
        caminho = filedialog.askopenfilename(
            title="Selecione a imagem da capa",
            filetypes=[("Imagens", "*.png *.jpg *.jpeg")],
            parent=self,
        )
        if not caminho:
            return
        self._nova_imagem_path = caminho
        self._mostrar_preview(caminho)

    def _remover_imagem(self):
        self._nova_imagem_path = "REMOVER"
        self.preview_imagem.configure(image=None, text="Nenhuma imagem selecionada")

    def _mostrar_preview(self, caminho):
        try:
            with Image.open(caminho) as img:
                img = img.convert("RGBA")
                img.thumbnail((260, 180))
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self.preview_imagem.configure(image=ctk_img, text="")
            self.preview_imagem.image = ctk_img  # mantém referência viva
        except Exception:
            messagebox.showwarning("Aviso", "Não foi possível abrir essa imagem.", parent=self)

    def _salvar(self):
        novo_config = {
            "usar_capa": bool(self.chk_usar_capa.get()),
            "tem_imagem": self.app.config_capa.get("tem_imagem", False),
        }

        if self._nova_imagem_path == "REMOVER":
            novo_config["tem_imagem"] = False
            try:
                os.remove(caminho_imagem_capa())
            except OSError:
                pass
        elif self._nova_imagem_path:
            try:
                with Image.open(self._nova_imagem_path) as img:
                    img.convert("RGB").save(caminho_imagem_capa(), "PNG")
                novo_config["tem_imagem"] = True
            except Exception as erro:
                messagebox.showerror("Erro", f"Não foi possível salvar a imagem:\n{erro}", parent=self)
                return

        if novo_config["usar_capa"] and not novo_config["tem_imagem"]:
            messagebox.showwarning(
                "Aviso", "Selecione uma imagem antes de ativar a capa.", parent=self
            )
            return

        salvar_config_capa(novo_config)
        self.app.config_capa = novo_config
        self.app._atualizar_label_capa()
        self.destroy()


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------
def main():
    app = GeradorPDFApp()
    app.mainloop()


if __name__ == "__main__":
    main()
