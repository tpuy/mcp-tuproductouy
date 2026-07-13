#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Server — TuProductoUY × BotMaker
=====================================
Expone 3 tools MCP sobre catálogo y stock.
Los datos se actualizan una vez al día desde Google Drive.

Endpoints:
  GET  /mcp         → tools/list
  POST /mcp         → tools/call
  GET  /mcp/health  → healthcheck
"""

import os
import csv
import json
import time
import urllib.request
import io
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# ===================== CONFIGURACIÓN =====================
API_KEY      = os.environ.get("MCP_API_KEY", "cambiar-esta-clave-secreta")
PORT         = int(os.environ.get("PORT", 8080))
CATALOG_URL  = os.environ.get(
    "CATALOG_URL",
    "https://drive.google.com/uc?export=download&id=1En6gQNkakNU1BhubUiZqDDDlUlllF7vN"
)
CATALOG_CSV  = "productos_mcp.csv"                  # archivo local (fallback)
REFRESH_SECS = 86400                                # recarga el CSV una vez por día

# ===================== CARGA DE DATOS =====================

_catalog  = {}
_load_ts  = 0

def _to_float(v):
    try:
        return float(str(v).replace(',', '.').strip())
    except Exception:
        return 0.0

def _to_int(v):
    try:
        return int(float(str(v).replace(',', '.').strip()))
    except Exception:
        return 0

def _parse_csv(content_str):
    """Parsea el CSV y devuelve dict SKU → producto."""
    catalog = {}
    reader = csv.DictReader(io.StringIO(content_str))
    for row in reader:
        sku = row.get('ID', '').strip()
        if not sku:
            continue
        nombre = row.get('Nombre', '').strip()
        if not nombre or 'ENVIOS' in nombre.upper():
            continue
        moneda_raw = row.get('Moneda', '$').strip()
        moneda = 'USD' if moneda_raw not in ('$', 'UYU', 'pesos') else 'UYU'
        catalog[sku] = {
            'id':            sku,
            'nombre':        nombre,
            'categoria':     row.get('Categoria', '').strip(),
            'subcategoria':  row.get('Subcategoria', '').strip(),
            'marca':         row.get('Marca', '').strip(),
            'talle':         row.get('Talle', '').strip(),
            'color':         row.get('Color', '').strip(),
            'descripcion':   row.get('Descripcion', '').strip(),
            'url':           row.get('URL_Producto', '').strip(),
            'ubicacion':     row.get('Ubicacion', '').strip(),
            'ubicacion_dep': row.get('UbicacionDep', '').strip(),
            'precio':        _to_float(row.get('Precio', 0)),
            'precio_m':      _to_float(row.get('PrecioMayor', 0)),
            'precio_d':      _to_float(row.get('PrecioDistrib', 0)),
            'moneda':        moneda,
            'stock':         _to_int(row.get('Stock', 0)),
            'stock_tienda':  _to_int(row.get('Stock_Tienda', 0)),
            'stock_funsa':   _to_int(row.get('Stock_Funsa', 0)),
            'disponible':    _to_int(row.get('Stock', 0)) > 0,
        }
    return catalog


def load_catalog(force=False):
    """Carga o recarga el catálogo. Si hay URL de Drive, lo descarga; si no, usa el archivo local."""
    global _catalog, _load_ts

    now = time.time()
    if not force and _catalog and (now - _load_ts) < REFRESH_SECS:
        return  # datos vigentes

    # Intentar desde Google Drive
    if CATALOG_URL:
        try:
            req = urllib.request.Request(CATALOG_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=20) as r:
                content = r.read().decode('utf-8-sig')
            _catalog = _parse_csv(content)
            _load_ts = now
            print(f"✅ Catálogo cargado desde Drive: {len(_catalog):,} productos")
            return
        except Exception as e:
            print(f"⚠ No se pudo bajar desde Drive: {e}. Usando archivo local.")

    # Fallback: archivo local
    if os.path.exists(CATALOG_CSV):
        with open(CATALOG_CSV, newline='', encoding='utf-8-sig') as f:
            _catalog = _parse_csv(f.read())
        _load_ts = now
        print(f"✅ Catálogo cargado desde archivo local: {len(_catalog):,} productos")
    else:
        print("❌ No se encontró el catálogo. El servidor responderá sin datos.")


# ===================== TOOLS MCP =====================

def fmt_precio(precio, moneda):
    if moneda == 'USD':
        return f"USD {precio:.2f}"
    return f"${precio:,.0f} UYU"


def tool_search_products(args):
    query    = args.get('query', '').upper().strip()
    category = args.get('category', '').upper().strip()
    limit    = min(int(args.get('limit', 5)), 10)

    if not query and not category:
        return "Por favor indicá qué producto buscás."

    load_catalog()
    results = []

    for sku, p in _catalog.items():
        nombre  = p['nombre'].upper()
        cat_str = (p['categoria'] + ' ' + p['subcategoria'] + ' ' + p['marca']).upper()

        if category and category not in cat_str:
            continue
        if query and not all(w in nombre or w in cat_str for w in query.split()):
            continue

        results.append(p)
        if len(results) >= limit:
            break

    if not results:
        return f"No encontré productos para '{args.get('query', '')}'. Probá con otra palabra clave."

    lines = [f"Encontré {len(results)} producto(s):\n"]
    for i, p in enumerate(results, 1):
        disp = "✅ Disponible" if p['disponible'] else "❌ Sin stock"
        lines.append(
            f"{i}. {p['nombre']}\n"
            f"   Precio: {fmt_precio(p['precio'], p['moneda'])} | {disp}\n"
            f"   🔗 {p['url']}"
        )
    return '\n'.join(lines)


def tool_get_product_details(args):
    product_id   = args.get('product_id', '').strip()
    product_name = args.get('product_name', '').upper().strip()

    if not product_id and not product_name:
        return "Necesito el ID o nombre del producto."

    load_catalog()

    if product_id:
        p = _catalog.get(product_id)
        if not p:
            p = next((v for k, v in _catalog.items() if product_id.upper() in k.upper()), None)
    else:
        p = next((v for v in _catalog.values() if product_name in v['nombre'].upper()), None)

    if not p:
        return f"No encontré el producto '{product_id or product_name}'."

    disp  = "✅ Disponible" if p['disponible'] else "❌ Sin stock"
    extra = ''
    if p.get('talle'):      extra += f"\nTalle: {p['talle']}"
    if p.get('color'):      extra += f"\nColor: {p['color']}"
    if p.get('descripcion'): extra += f"\nDescripción: {p['descripcion']}"

    return (
        f"{p['nombre']}\n"
        f"SKU: {p['id']}\n"
        f"Marca: {p['marca']}\n"
        f"Categoría: {p['categoria']} / {p['subcategoria']}"
        f"{extra}\n"
        f"Precio público: {fmt_precio(p['precio'], p['moneda'])}\n"
        f"Precio mayorista: {fmt_precio(p['precio_m'], p['moneda'])}\n"
        f"Estado: {disp} "
        f"({p['stock']} uds — tienda: {p['stock_tienda']}, depósito: {p['stock_funsa']})\n"
        f"🔗 {p['url']}"
    )


def tool_check_stock(args):
    product_id = args.get('product_id', '').strip()
    variant    = args.get('variant', '').upper().strip()

    if not product_id:
        return "Necesito el ID del producto."

    load_catalog()
    p = _catalog.get(product_id)
    if not p:
        return f"No encontré el producto con ID '{product_id}'."

    disp  = "✅ Disponible" if p['disponible'] else "❌ Sin stock"
    texto = (
        f"Stock para {p['nombre']}:\n"
        f"- Tienda: {p['stock_tienda']} unidades\n"
        f"- Depósito Funsa: {p['stock_funsa']} unidades\n"
        f"- Total: {p['stock']} unidades | {disp}"
    )

    if variant:
        nombre_base = p['nombre'][:25]
        variantes = [
            f"  • {v['nombre']}: {v['stock']} uds"
            for k, v in _catalog.items()
            if k != product_id and nombre_base in v['nombre']
        ][:5]
        if variantes:
            texto += "\n\nVariantes relacionadas:\n" + '\n'.join(variantes)

    return texto


# ===================== SERVIDOR HTTP =====================

TOOLS_LIST = {
    "jsonrpc": "2.0",
    "result": {
        "tools": [
            {
                "name": "search_products",
                "description": "Busca productos en el catálogo de TuProductoUY por nombre, categoría o marca.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query":    {"type": "string", "description": "Texto de búsqueda. Ej: 'pelota futsal', 'mancuerna 20kg'"},
                        "category": {"type": "string", "description": "Filtro por categoría o marca. Ej: 'Gym', 'RHINO', 'Natación'"},
                        "limit":    {"type": "integer", "description": "Máximo de resultados. Default 5, máximo 10."}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_product_details",
                "description": "Retorna detalles completos de un producto: precio, stock, descripción y link.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "product_id":   {"type": "string", "description": "SKU del producto."},
                        "product_name": {"type": "string", "description": "Nombre parcial del producto."}
                    },
                    "oneOf": [{"required": ["product_id"]}, {"required": ["product_name"]}]
                }
            },
            {
                "name": "check_stock",
                "description": "Consulta el stock de un producto separado por tienda y depósito.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string", "description": "SKU del producto."},
                        "variant":    {"type": "string", "description": "Variante. Ej: 'talle 42', 'color azul'"}
                    },
                    "required": ["product_id"]
                }
            }
        ]
    }
}


class MCPHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}")

    def send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def check_auth(self):
        return self.headers.get('Authorization', '') == f'Bearer {API_KEY}'

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == '/mcp/health':
            self.send_json(200, {
                "status": "ok",
                "productos": len(_catalog),
                "ultima_carga": time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(_load_ts)) if _load_ts else "nunca"
            })
            return

        if path == '/mcp':
            # Discovery: no requiere auth, retorna tools en formato simple
            self.send_json(200, {
                "tools": TOOLS_LIST["result"]["tools"]
            })
            return

        self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        if urlparse(self.path).path != '/mcp':
            self.send_json(404, {"error": "Not found"})
            return

        if not self.check_auth():
            self.send_json(401, {"error": "Unauthorized"})
            return

        length = int(self.headers.get('Content-Length', 0))
        try:
            req = json.loads(self.rfile.read(length))
        except Exception:
            self.send_json(400, {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}})
            return

        req_id = req.get('id')
        method = req.get('method', '')
        params = req.get('params', {})

        if method == 'initialize':
            self.send_json(200, {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "TuProductoUY MCP", "version": "1.0.0"}
                }
            })
            return

        if method == 'tools/list':
            self.send_json(200, {**TOOLS_LIST, "id": req_id})
            return

        if method == 'tools/call':
            tool_name = params.get('name', '')
            args      = params.get('arguments', {})
            try:
                if tool_name == 'search_products':
                    text = tool_search_products(args)
                elif tool_name == 'get_product_details':
                    text = tool_get_product_details(args)
                elif tool_name == 'check_stock':
                    text = tool_check_stock(args)
                else:
                    text = f"Tool '{tool_name}' no existe."
            except Exception as e:
                text = f"Error al ejecutar '{tool_name}': {e}"

            self.send_json(200, {
                "jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": text}]}
            })
            return

        self.send_json(400, {
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Method '{method}' not found"}
        })


# ===================== MAIN =====================

if __name__ == '__main__':
    print("=" * 50)
    print("  TuProductoUY MCP Server")
    print("=" * 50)
    load_catalog(force=True)
    server = HTTPServer(('0.0.0.0', PORT), MCPHandler)
    print(f"\n🚀 Corriendo en puerto {PORT}\n")
    server.serve_forever()
