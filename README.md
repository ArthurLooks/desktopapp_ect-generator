# Gerador de PDF

Aplicativo desktop leve para compilar várias imagens em um único PDF bem
formatado — sem precisar de internet, conta ou instalação de programas
pesados. Selecione as imagens, ajuste a ordem, e gere um PDF em segundos.

**Alguns usos comuns:**

- QA / Testes, documentar evidências de casos de teste para anexar no ALM Octane,
  Jira, TestRail ou qualquer ferramenta de gestão de testes.
- Manuais e tutoriais visuais (passo a passo em imagens).
- Relatórios fotográficos (vistorias, inspeções, obras).
- Portfólios e comprovantes diversos.

Qualquer coisa que hoje você resolveria "juntando prints numa pasta e
mandando um por um" este app resolve com um PDF único, organizado e
pronto para compartilhar.

Compatível com Python 3.10, 3.11 e 3.12.

---

## 1. Rodando o app pelo terminal (modo desenvolvimento)

### 1.1. Pré-requisitos

- Python 3.10+ instalado ([python.org](https://www.python.org/downloads/))
- Gerenciador de pacotes [uv](https://docs.astral.sh/uv/) instalado
- No Windows, ao instalar o Python marque a opção **"Add python.exe to PATH"**

### 1.2. Instalação das dependências

Abra um terminal na pasta do projeto e rode:

```bash
uv sync --group dev
```

> **Nota**
> `tkinterdnd2` habilita o "arrastar e soltar" arquivos direto na
> janela. Se a instalação dessa lib falhar no seu ambiente, pode remover a
> linha do `pyproject.toml` que o app detecta a ausência dela automaticamente
> e continua funcionando normalmente, só sem esse recurso (você ainda usa os
> botões "Selecionar Pasta" / "Adicionar Arquivos").

### 1.3. Executar

```bash
uv run main.py
```

---

## 2. Como usar

1. Clique em **"Selecionar Pasta"** (carrega todas as imagens de uma pasta)
   ou **"Adicionar Arquivos"** (seleciona imagens específicas) — os dois
   abrem a janela **nativa** do sistema operacional. Você também pode
   arrastar os arquivos direto do Explorador de Arquivos para a galeria.
2. As imagens aparecem como **cartões de tamanho padronizado**, cada um com
   miniatura, numeração de ordem e nome do arquivo — facilita identificar
   cada imagem mesmo quando o nome é genérico (ex: prints de tela).
3. Elas são ordenadas automaticamente por nome (ordenação natural:
   `imagem_2` vem antes de `imagem_10`). Se preferir, use **"Ordenar por
   Data"** para reordenar pela data de criação do arquivo.
4. Ajuste a ordem manualmente:
   - Clique em um cartão para selecioná-lo (**Ctrl+clique** para vários,
     **Shift+clique** para um intervalo) — a borda azul marca a seleção;
   - Use **"Mover Antes"** / **"Mover Depois"** para reordenar os
     selecionados um passo antes/depois na sequência final do PDF;
   - Ou **arraste o cartão** com o mouse até a posição desejada.
5. Use **"Remover Selecionados"** para tirar apenas os cartões marcados, ou
   **"Remover Todos"** para limpar a galeria inteira (pede confirmação).
6. (Opcional) Preencha **"Título do Documento"** que aparece no cabeçalho de
   cada página do PDF (ex: o ID de um caso de teste, ou o nome do relatório).
7. (Opcional) Clique em **"Configurar Capa"** para escolher uma imagem que
   vai virar a primeira página do PDF (uma capa, um índicem, a imagem que você preferir). Essa configuração **fica salva na sua máquina**, continua disponível da próxima vez que você abrir o
   app, sem precisar selecionar de novo.
8. Clique em **"Gerar PDF"**, escolha onde salvar, e aguarde a barra de
   progresso. Cada imagem vira uma página A4, redimensionada
   proporcionalmente para não cortar nem distorcer, numerada como "Imagem X
   de Y", **o nome original do arquivo nunca é impresso no PDF**, já que
   nomes de arquivo (principalmente de prints de tela) costumam ser
   genéricos e sem valor para quem revisa o documento depois.

### Sobre desempenho

- Miniaturas e imagens do PDF são processadas em **paralelo** (várias ao
  mesmo tempo) em vez de uma por vez, o que acelera bastante o carregamento
  e a geração quando há muitos arquivos ou eles estão numa pasta de rede.
- Cada imagem é reduzida para a resolução real necessária numa página A4
  (150 DPI) antes de entrar no PDF, isso evita embutir pixels que nunca serão
  exibidos, deixando a geração mais rápida e o arquivo final bem menor,
  sem perda perceptível de qualidade.
- A interface nunca trava: tanto o carregamento de imagens quanto a geração
  do PDF rodam em segundo plano.

### Sobre confiabilidade

- Arquivos cujo caminho completo passa de 260 caracteres (um limite prático
  que costuma causar falha de leitura em diversos sistemas, não só no
  Windows) são detectados e ignorados **antes** de tentar abri-los, com um
  aviso claro explicando o motivo e como resolver.
- Se uma imagem estiver corrompida ou for removida do disco entre a seleção
  e a geração, ela é pulada (com aviso ao final) em vez de travar ou
  invalidar o PDF inteiro.

---

## 3. Gerando o executável (.exe) portátil com PyInstaller

> **Importante:** o PyInstaller compila para o sistema operacional em que ele
> é executado. Para gerar um `.exe` do Windows, rode o comando abaixo **em uma
> máquina Windows** (com o mesmo ambiente/dependências instaladas).

Na pasta do projeto:

```bash
pyinstaller --onefile --windowed --name "GeradorPDF" ^
  --icon=favicon.ico ^
  --add-data "favicon.ico;." ^
  --collect-all customtkinter ^
  --collect-all tkinterdnd2 ^
  main.py
```

(No Linux/Mac, troque o `^` de quebra de linha por `\` e `;.` por `:.`)

### O que cada flag faz:

- `--onefile`: empacota tudo em um único `.exe`, fácil de copiar para
  qualquer máquina (portátil, sem instalação).
- `--windowed`: não abre o console preto do CMD por trás da interface gráfica.
- `--icon` / `--add-data`: define o ícone do arquivo `.exe` e também embute
  o `.ico` para uso como ícone da janela/barra de tarefas em tempo de
  execução (veja `caminho_do_recurso()` no código).
- `--collect-all customtkinter`: garante que os arquivos de tema (`.json`) do
  CustomTkinter sejam incluídos no executável (sem isso, o app abre em branco
  ou dá erro de "theme not found").
- `--collect-all tkinterdnd2`: inclui as bibliotecas nativas do TKDND
  necessárias para o drag-and-drop funcionar no `.exe`.

### Resultado

O executável final fica em `dist/GeradorPDF.exe`. Copie apenas esse arquivo
para onde precisar usá-lo — ele já contém o Python e todas as dependências
embutidas, sem precisar instalar nada na máquina de destino.

### Onde ficam as preferências salvas (capa personalizada)

O app grava a configuração de capa em `%APPDATA%\GeradorPDF_QA\` no Windows
(ou na pasta pessoal do usuário em outros sistemas), nunca ao lado do
`.exe`, que pode estar num local somente leitura (ex: pasta compartilhada em
rede). Isso significa que a configuração é por usuário/máquina, e persiste
entre atualizações do executável.

### Dica de solução de problemas

Se o `.exe` gerado não abrir (fechar sozinho sem erro visível), rode uma vez
sem a flag `--windowed` para ver a mensagem de erro no console, corrija, e
gere novamente com `--windowed`.

---

## 4. Estrutura do projeto

```
.
├── main.py           # Código-fonte da aplicação (interface, lógica, geração de PDF)
├── icones.py         # Biblioteca de ícones da interface (desenhados via Pillow)
├── favicon.ico        # Ícone do app (janela + executável)
├── pyproject.toml     # Dependências (runtime + build)
└── README.md          # Este arquivo
```

O código é organizado em:

- **Funções utilitárias** (ordenação natural, cálculo de redimensionamento,
  limite de caminho, persistência de configuração) — sem dependência da
  interface, fáceis de testar isoladamente.
- **`icones.py`** — biblioteca própria de ícones (desenhados com Pillow, não
  emojis), garantindo tamanho e estilo idênticos em todos os botões,
  independente do sistema operacional.
- **Classe `GeradorPDFApp`** — toda a lógica de interface e orquestração,
  dividida em métodos pequenos e comentados (montagem de UI, carregamento de
  arquivos, ordenação, galeria, geração de PDF).
- **Classe `JanelaConfigCapa`** — diálogo de configuração da capa
  personalizada (seleção de uma imagem), com persistência em disco.
- Carregamento de imagens e geração de PDF rodam em **threads separadas com
  pool de processamento paralelo**, para não travar a interface e acelerar
  o trabalho com muitos arquivos.
