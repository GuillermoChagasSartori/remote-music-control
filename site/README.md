# Site — Remote Music Control

Landing page estática (HTML/CSS/JS puro, sem build) para divulgar o instalador do
Remote Music Control.

## Deploy no Render (Static Site)

1. Acesse [render.com](https://render.com) e faça login.
2. Clique em **New** → **Static Site**.
3. Conecte este repositório do GitHub.
4. Configure:
   - **Root Directory**: `site`
   - **Build Command**: (deixe em branco)
   - **Publish Directory**: `.`
5. Clique em **Create Static Site**.

Não há dependências externas além das fontes do Google Fonts, carregadas via `<link>`
no `index.html` — nenhum passo de build é necessário.

## Estrutura

- `index.html` — página única
- `style.css` — estilos (tema escuro por padrão, tema claro via `prefers-color-scheme`)
- `script.js` — animação de entrada ao rolar a página (fade/slide-up)
- `web-ui.png` — captura de tela da interface web
