#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Server — TuProductoUY × BotMaker (Flask)
"""

import os, csv, json, time, urllib.request, io
from flask import Flask, request, jsonify

app = Flask(__name__)

# ===================== CONFIG =====================
API_KEY      = os.environ.get("MCP_API_KEY", "tpu-mcp-2026-abc123")
CATALOG_URL  = os.environ.get(
    "CATALOG_URL",
    "https://drive.google.com/uc?export=download&id=1En6gQNkakNU1BhubUiZqDDDlUlllF7vN"
)
CATALOG_CSV  = "productos_mcp.csv"
REFRESH_SECS = 86400

_catalog = {}
_load_ts = 0

# ===================== DATOS =====================

def _to_float(v):
    try: return float(str(v).replace(',', '.').strip())
    except: return 0.0

def _to_int(v):
    try: return int(float(str(v).replace(',', '.').strip()))
    except: return 0

def _parse_csv(content_str):
    catalog = {}
    reader = csv.DictReader(io.StringIO(content_str))
    for row in reader:
        sku = row.get('ID', '').strip()
        if not sku: continue
        nombre = row.get('Nombre', '').strip()
        if not nombre or 'ENVIOS' in nombre.upper(): continue
        moneda_raw = row.get('Moneda', '$').strip()
        moneda = 'USD' if moneda_raw not in ('$', 'UYU', 'pesos') else 'UYU'
        catalog[sku] = {
            'id': sku, 'nombre': nombre,
            'categoria': row.get('Categoria', '').strip(),
            'subcategoria': row.get('Subcategoria', '').strip(),
            'marca': row.get('Marca', '').strip(),
            'talle': row.get('Talle', '').strip(),
            'color': row.get('Color', '').strip(),
            'descripcion': row.get('Descripcion', '').strip(),
            'url': row.get('URL_Producto', '').strip(),
            'ubicacion': row.get('Ubicacion', '').strip(),
            'ubicacion_dep': row.get('UbicacionDep', '').strip(),
            'precio': _to_float(row.get('Precio', 0)),
            'precio_m': _to_float(row.get('PrecioMayor', 0)),
            'precio_d': _to_float(row.get('PrecioDistrib', 0)),
            'moneda': moneda,
            'stock': _to_int(row.get('Stock', 0)),
            'stock_tienda': _to_int(row.get('Stock_Tienda', 0)),
            'stock_funsa': _to_int(row.get('Stock_Funsa', 0)),
            'disponible': _to_int(row.get('Stock', 0)) > 0,
        }
    return catalog

def load_catalog(force=False):
    global _catalog, _load_ts
    now = time.time()
    if not force and _catalog and (now - _load_ts) < REFRESH_SECS:
        return
    try:
        req = urllib.request.Request(CATALOG_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=20) as r:
            content = r.read().decode('utf-8-sig')
        _catalog = _parse_csv(content)
        _load_ts = now
        print(f"Catálogo desde Drive: {len(_catalog)} productos")
        return
    except Exception as e:
        print(f"Drive error: {e}")
    if os.path.exists(CATALOG_CSV):
        with open(CATALOG_CSV, newline='', encoding='utf-8-sig') as f:
            _catalog = _parse_csv(f.read())
        _load_ts = now
        print(f"Catálogo local: {len(_catalog)} productos")

# ===================== TOOLS =====================

def fmt_precio(precio, moneda):
    return f"USD {precio:.2f}" if moneda == 'USD' else f"${precio:,.0f} UYU"

def tool_search_products(args):
    query    = args.get('query', '').upper().strip()
    category = args.get('category', '').upper().strip()
    limit    = min(int(args.get('limit', 5)), 10)
    load_catalog()
    results = []
    for sku, p in _catalog.items():
        nombre  = p['nombre'].upper()
        cat_str = (p['categoria'] + ' ' + p['subcategoria'] + ' ' + p['marca']).upper()
        if category and category not in cat_str: continue
        if query and not all(w in nombre or w in cat_str for w in query.split()): continue
        results.append(p)
        if len(results) >= limit: break
    if not results:
        return f"No encontré productos para '{args.get('query', '')}'. Probá con otra palabra clave."
    lines = [f"Encontré {len(results)} producto(s):\n"]
    for i, p in enumerate(results, 1):
        disp = "✅ Disponible" if p['disponible'] else "❌ Sin stock"
        lines.append(f"{i}. {p['nombre']}\n   Precio: {fmt_precio(p['precio'], p['moneda'])} | {disp}\n   🔗 {p['url']}")
    return '\n'.join(lines)

def tool_get_product_details(args):
    product_id   = args.get('product_id', '').strip()
    product_name = args.get('product_name', '').upper().strip()
    if not product_id and not product_name:
        return "Necesito el ID o nombre del producto."
    load_catalog()
    if product_id:
        p = _catalog.get(product_id) or next((v for k, v in _catalog.items() if product_id.upper() in k.upper()), None)
    else:
        p = next((v for v in _catalog.values() if product_name in v['nombre'].upper()), None)
    if not p:
        return f"No encontré el producto '{product_id or product_name}'."
    disp  = "✅ Disponible" if p['disponible'] else "❌ Sin stock"
    extra = ''
    if p.get('talle'):       extra += f"\nTalle: {p['talle']}"
    if p.get('color'):       extra += f"\nColor: {p['color']}"
    if p.get('descripcion'): extra += f"\nDescripción: {p['descripcion']}"
    return (f"{p['nombre']}\nSKU: {p['id']}\nMarca: {p['marca']}\n"
            f"Categoría: {p['categoria']} / {p['subcategoria']}{extra}\n"
            f"Precio público: {fmt_precio(p['precio'], p['moneda'])}\n"
            f"Precio mayorista: {fmt_precio(p['precio_m'], p['moneda'])}\n"
            f"Estado: {disp} ({p['stock']} uds — tienda: {p['stock_tienda']}, depósito: {p['stock_funsa']})\n"
            f"🔗 {p['url']}")

def tool_check_stock(args):
    product_id = args.get('product_id', '').strip()
    if not product_id: return "Necesito el ID del producto."
    load_catalog()
    p = _catalog.get(product_id)
    if not p: return f"No encontré el producto con ID '{product_id}'."
    disp = "✅ Disponible" if p['disponible'] else "❌ Sin stock"
    texto = (f"Stock para {p['nombre']}:\n- Tienda: {p['stock_tienda']} unidades\n"
             f"- Depósito Funsa: {p['stock_funsa']} unidades\n- Total: {p['stock']} unidades | {disp}")
    variant = args.get('variant', '').upper()
    if variant:
        base = p['nombre'][:25]
        vars_ = [f"  • {v['nombre']}: {v['stock']} uds" for k, v in _catalog.items() if k != product_id and base in v['nombre']][:5]
        if vars_: texto += "\n\nVariantes relacionadas:\n" + '\n'.join(vars_)
    return texto

# ===================== TOOLS SCHEMA =====================

TOOLS = [
    {
        "name": "search_products",
        "description": "Busca productos en el catálogo de TuProductoUY por nombre, categoría o marca.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":    {"type": "string", "description": "Texto de búsqueda. Ej: 'pelota futsal', 'mancuerna 20kg'"},
                "category": {"type": "string", "description": "Filtro por categoría o marca. Ej: 'Gym', 'RHINO'"},
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
                "variant":    {"type": "string", "description": "Variante. Ej: 'talle 42'"}
            },
            "required": ["product_id"]
        }
    }
]

# ===================== RUTAS =====================

def check_auth():
    auth = request.headers.get('Authorization', '')
    return auth == f'Bearer {API_KEY}'

@app.route('/mcp/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "productos": len(_catalog),
        "ultima_carga": time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(_load_ts)) if _load_ts else "nunca"
    })

@app.route('/mcp', methods=['GET'])
def mcp_discovery():
    # Discovery sin auth — BotMaker lo llama para ver las tools disponibles
    return jsonify({"tools": TOOLS})

@app.route('/mcp', methods=['POST'])
def mcp_call():
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401

    data    = request.get_json(force=True, silent=True) or {}
    req_id  = data.get('id')
    method  = data.get('method', '')
    params  = data.get('params', {})

    if method == 'initialize':
        return jsonify({
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "TuProductoUY MCP", "version": "1.0.0"}
            }
        })

    if method == 'tools/list':
        return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})

    if method == 'tools/call':
        tool_name = params.get('name', '')
        args      = params.get('arguments', {})
        try:
            if tool_name == 'search_products':       text = tool_search_products(args)
            elif tool_name == 'get_product_details': text = tool_get_product_details(args)
            elif tool_name == 'check_stock':         text = tool_check_stock(args)
            else: text = f"Tool '{tool_name}' no existe."
        except Exception as e:
            text = f"Error: {e}"
        return jsonify({
            "jsonrpc": "2.0", "id": req_id,
            "result": {"content": [{"type": "text", "text": text}]}
        })

    return jsonify({"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Method '{method}' not found"}}), 400

# ===================== MAIN =====================

if __name__ == '__main__':
    load_catalog(force=True)
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 TuProductoUY MCP Server corriendo en puerto {port}")
    app.run(host='0.0.0.0', port=port)
