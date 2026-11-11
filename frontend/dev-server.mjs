import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { dirname, extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const host = process.env.HOST || '127.0.0.1';
const port = Number(process.env.PORT || '5173');
const types = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

createServer(async (req, res) => {
  try {
    if (!['GET', 'HEAD'].includes(req.method)) {
      res.writeHead(405, { 'allow': 'GET, HEAD' }).end('Method not allowed');
      return;
    }
    const url = new URL(req.url, `http://${host}:${port}`);
    const requested = decodeURIComponent(url.pathname);
    // Never serve dotfiles such as .env, .git or .gitignore from the dev server.
    if (requested.split('/').some((segment) => segment.startsWith('.') && segment !== '.' && segment !== '..')) {
      res.writeHead(403).end('Forbidden');
      return;
    }
    const path = resolve(join(root, `.${requested}`));
    if (path !== root && !path.startsWith(root + sep)) {
      res.writeHead(403).end('Forbidden');
      return;
    }
    let file = path;
    const info = await stat(file).catch(() => null);
    if (!info?.isFile()) {
      if (requested === '/' || !extname(requested)) file = join(root, 'index.html');
      else { res.writeHead(404).end('Not found'); return; }
    }
    const body = await readFile(file);
    res.writeHead(200, {
      'content-type': types[extname(file)] || 'application/octet-stream',
      'cache-control': 'no-store',
      'x-content-type-options': 'nosniff',
    });
    if (req.method === 'HEAD') res.end();
    else res.end(body);
  } catch {
    res.writeHead(400).end('Bad request');
  }
}).listen(port, host, () => {
  console.log(`EnergyTool frontend: http://${host}:${port}`);
  console.log('FastAPI backend expected: http://127.0.0.1:8000');
});
