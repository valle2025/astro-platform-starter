# Astro on Netlify Platform Starter

[Live Demo](https://astro-platform-starter.netlify.app/)

A modern starter based on Astro.js, Tailwind, and [Netlify Core Primitives](https://docs.netlify.com/core/overview/#develop) (Edge Functions, Image CDN, Blob Store).

## Astro Commands

All commands are run from the root of the project, from a terminal:

| Command                   | Action                                           |
| :------------------------ | :----------------------------------------------- |
| `npm install`             | Installs dependencies                            |
| `npm run dev`             | Starts local dev server at `localhost:4321`      |
| `npm run build`           | Build your production site to `./dist/`          |
| `npm run preview`         | Preview your build locally, before deploying     |
| `npm run astro ...`       | Run CLI commands like `astro add`, `astro check` |
| `npm run astro -- --help` | Get help using the Astro CLI                     |

## Deploying to Netlify

[![Deploy to Netlify](https://www.netlify.com/img/deploy/button.svg)](https://app.netlify.com/start/deploy?repository=https://github.com/netlify-templates/astro-platform-starter)

## Developing Locally

| Prerequisites                                                                |
| :--------------------------------------------------------------------------- |
| [Node.js](https://nodejs.org/) v18.14+.                                      |
| (optional) [nvm](https://github.com/nvm-sh/nvm) for Node version management. |

1. Clone this repository, then run `npm install` in its root directory.

2. For the starter to have full functionality locally (e.g. edge functions, blob store), please ensure you have an up-to-date version of Netlify CLI. Run:

```
npm install netlify-cli@latest -g
```

3. Link your local repository to the deployed Netlify site. This will ensure you're using the same runtime version for both local development and your deployed site.

```
netlify link
```

4. Then, run the Astro.js development server via Netlify CLI:

```
netlify dev
```

If your browser doesn't navigate to the site automatically, visit [localhost:8888](http://localhost:8888).

## Perplexity MCP Server

This repo ships a project-scoped MCP config (`.mcp.json`) for the [official Perplexity MCP server](https://github.com/perplexityai/modelcontextprotocol), which gives Claude Code real-time web search, reasoning, and research tools.

The API key is **not** stored in the repo — `.mcp.json` expands `${PERPLEXITY_API_KEY}` from your environment. Get a key at [console.perplexity.ai](https://console.perplexity.ai) and export it before starting Claude Code:

```bash
export PERPLEXITY_API_KEY="your_key_here"
claude
```

Claude Code asks for approval the first time it loads a project-scoped server. Verify with `/mcp` or:

```bash
claude mcp list
```

### Alternatives

Register the local (stdio) server just for yourself, outside the repo:

```bash
claude mcp add perplexity --env PERPLEXITY_API_KEY="your_key_here" -- npx -y @perplexity-ai/mcp-server
```

Or use Perplexity's hosted server over HTTP — nothing to install or update:

```bash
claude mcp add --transport http perplexity https://api.perplexity.ai/mcp --header "Authorization: Bearer YOUR_API_KEY"
```

Optional environment variables: `PERPLEXITY_TIMEOUT_MS` (default `300000`), `PERPLEXITY_BASE_URL`, `PERPLEXITY_LOG_LEVEL`, `PERPLEXITY_PROXY`.
