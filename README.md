# Gerador de ECT (Evidências de Caso de Teste)

Aplicativo desktop leve para compilar screenshots de evidências de teste em um
único PDF, pronto para anexar no ALM Octane (ou qualquer ferramenta de QA).

Compátivel com Python 3.10, 3.11 e 3.12.

---

## 1. Rodando o app pelo terminal (modo desenvolvimento)

### 1.1. Pré-requisitos
- Python 3.10+ instalado ([python.org](https://www.python.org/downloads/))
- Gerenciador de pacotes UV instalado
- No Windows, ao instalar o Python marque a opção **"Add python.exe to PATH"**

### 1.2. Instalação das dependências
Abra um terminal na pasta do projeto e rode:

```bash
uv init

uv sync --group dev
```

> **Nota:** `tkinterdnd2` habilita o "arrastar e soltar" arquivos direto na
> janela. Se a instalação dessa lib falhar no seu ambiente, pode remover a
> linha do `pyproject.toml` — o app detecta a ausência dela automaticamente
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
   abrem a janela **nativa** do sistema operacional (Explorador de Arquivos
   no Windows, Finder no macOS). Você também pode arrastar os arquivos
   direto do Explorer para a galeria.
2. As imagens aparecem como **cartões com miniatura** (prévia visual da
   imagem, numeração de ordem e nome do arquivo), facilitando identificar
   cada screenshot mesmo quando o nome é genérico.
3. Elas são ordenadas automaticamente por nome (ordenação natural:
   `evidencia_2` vem antes de `evidencia_10`). Se preferir, use o botão
   **"Ordenar por Data"** para reordenar pela data de criação do arquivo.
4. Ajuste a ordem manualmente:
   - Clique em um cartão para selecioná-lo (**Ctrl+clique** para selecionar
     vários, **Shift+clique** para selecionar um intervalo) — a borda azul
     mostra o que está selecionado;
   - Use **"◀ Mover Antes"** / **"Mover Depois ▶"** para reordenar os
     selecionados um passo antes/depois na sequência;
   - Ou simplesmente **arraste o cartão** com o mouse até a posição desejada.
   - O scroll do mouse funciona em qualquer ponto da galeria, mesmo em
     cima de um cartão.
5. Use **"Remover Selecionados"** para tirar apenas os cartões marcados, ou
   **"Remover Todos"** para limpar a galeria inteira (pede confirmação).
6. (Opcional) Preencha o campo **"ID / Nome do Caso de Teste"** — esse texto
   aparece no cabeçalho de cada página do PDF.
7. Clique em **"Gerar ECT (PDF)"**, escolha onde salvar (janela nativa
   também), e aguarde a barra de progresso concluir. Cada imagem vira uma
   página em A4, redimensionada proporcionalmente para não cortar nem
   distorcer, numerada como "Evidência X de Y" — **o nome original do
   arquivo nunca é impresso no PDF**, já que nomes de screenshot costumam
   ser genéricos e sem valor para quem revisa o documento.

O app processa uma imagem por vez durante a geração do PDF (não carrega
todas na memória simultaneamente), então funciona bem mesmo com 30+
screenshots em alta resolução. As miniaturas da galeria também são pequenas
(até 150x150px) e ficam em cache, então reordenar a lista não reprocessa as
imagens originais.

---

## 3. Gerando o executável (.exe) portátil com PyInstaller

> **Importante:** o PyInstaller compila para o sistema operacional em que ele
> é executado. Para gerar um `.exe` do Windows, rode o comando abaixo **em uma
> máquina Windows** (com o mesmo ambiente virtual/dependências instaladas).

Na pasta do projeto, com o ambiente virtual ativado:

```bash
pyinstaller --onefile --windowed --name "GeradorECT" ^
  --icon=favicon.ico ^
  --add-data "favicon.ico;." ^
  --collect-all customtkinter ^
  --collect-all tkinterdnd2 ^
  main.py
```

(No Linux/Mac, troque o `^` de quebra de linha por `\`.)

### O que cada flag faz:
- `--onefile`: empacota tudo em um único `.exe`, fácil de copiar para
  qualquer máquina (portátil, sem instalação).
- `--windowed`: não abre o console preto do CMD por trás da interface gráfica.
- `--collect-all customtkinter`: garante que os arquivos de tema (`.json`) do
  CustomTkinter sejam incluídos no executável (sem isso, o app abre em branco
  ou dá erro de "theme not found").
- `--collect-all tkinterdnd2`: inclui as bibliotecas nativas do TKDND
  necessárias para o drag-and-drop funcionar no `.exe`.

### Resultado
O executável final fica em `dist/GeradorECT.exe`. Copie apenas esse arquivo
para onde precisar usá-lo — ele já contém o Python e todas as dependências
embutidas, sem precisar instalar nada na máquina de destino.

### Ícone personalizado (opcional)
Se quiser um ícone customizado, adicione `--icon=caminho\para\icone.ico` ao
comando acima (o arquivo precisa ser `.ico`).

### Dica de solução de problemas
Se o `.exe` gerado não abrir (fechar sozinho sem erro visível), rode uma vez
sem a flag `--windowed` para ver a mensagem de erro no console, corrija, e
gere novamente com `--windowed`.

---

## 4. Estrutura do projeto

```
.
├── main.py     # Código-fonte completo da aplicação
├── pyproject.toml   # Dependências (runtime + build)
└── README.md          # Este arquivo
```

O código é organizado em:
- **Funções utilitárias** (ordenação natural, cálculo de redimensionamento)
  — sem dependência da interface, fáceis de testar isoladamente.
- **Classe `GeradorECTApp`** — toda a lógica de interface e orquestração,
  dividida em métodos pequenos e comentados (montagem de UI, carregamento de
  arquivos, ordenação, geração de PDF).
- Geração de PDF roda em **thread separada** para a interface não travar
  durante o processamento de várias imagens.
