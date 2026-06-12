# ==================================================
# IMPORTS
# ==================================================
import os
import json
import re
import sys
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Configurar encoding do console para Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# NOVA BIBLIOTECA DO GOOGLE
try:
    from google import genai
except ImportError:
    print("❌ Instale a biblioteca: pip install google-genai")
    sys.exit(1)

# ==================================================
# CONFIGURAÇÕES INICIAIS
# ==================================================

# Carregar .env
load_dotenv()

# CORREÇÃO: Procura o JSON na mesma pasta do app.py
# Obtém o diretório ONDE o app.py está localizado
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUTOS_PATH = os.path.join(BACKEND_DIR, 'produtos.json')

print(f"📂 Procurando produtos.json em: {PRODUTOS_PATH}")

# Chave da API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("❌ GEMINI_API_KEY não encontrada no arquivo .env")
    print("   Crie o arquivo .env com: GEMINI_API_KEY=sua_chave_aqui")
    sys.exit(1)

# Configurar cliente Gemini
client = genai.Client(api_key=GEMINI_API_KEY)

# Flask
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=False)

# ==================================================
# CARREGAR PRODUTOS DO JSON
# ==================================================

def carregar_produtos():
    """Carrega a lista de produtos do arquivo produtos.json"""
    try:
        with open(PRODUTOS_PATH, 'r', encoding='utf-8') as f:
            dados = json.load(f)

        # Suporta lista direta [...] ou objeto {"celulares": [...]}
        if isinstance(dados, list):
            raw = dados
        elif isinstance(dados, dict):
            raw = next((v for v in dados.values() if isinstance(v, list)), [])
        else:
            raw = []

        # Normaliza campos para o padrão do app
        produtos = []
        for p in raw:
            produtos.append({
                "nome":         f"{p.get('marca', '')} {p.get('modelo', p.get('nome', ''))}".strip(),
                "preco":        p.get('preco'),
                "memoria":      p.get('armazenamento', p.get('memoria', 'N/A')),
                "ram":          p.get('memoria_ram',   p.get('ram', 'N/A')),
                "tipo":         p.get('status',        p.get('tipo', 'Smartphone')),
                "cores":        [p['cor']] if p.get('cor') else p.get('cores', []),
                "promocao":     p.get('promocao', False),
                "preco_antigo": p.get('preco_antigo'),
            })

        print(f"✅ Produtos carregados com sucesso: {len(produtos)} itens")
        print("\n📱 Produtos disponíveis:")
        for i, p in enumerate(produtos[:5]):
            print(f"   {i+1}. {p.get('nome', 'N/A')} - R$ {p.get('preco', 'N/A')}")
        if len(produtos) > 5:
            print(f"   ... e mais {len(produtos)-5} produtos")

        return produtos
    except FileNotFoundError:
        print(f"❌ ERRO: Arquivo não encontrado em: {PRODUTOS_PATH}")
        print("\n💡 SOLUÇÃO:")
        print("   1. Coloque o arquivo 'produtos.json' na mesma pasta que este app.py")
        print(f"   2. Pasta atual: {BACKEND_DIR}")
        print("   3. Ou mova o arquivo para esta pasta")
        return []
    except json.JSONDecodeError as e:
        print(f"❌ ERRO: Arquivo JSON inválido: {str(e)}")
        return []

PRODUTOS = carregar_produtos()

# ==================================================
# FUNÇÃO DE BUSCA
# ==================================================

def buscar_produtos_relevantes(pergunta_usuario, limite=5):
    """Busca produtos relevantes baseado na pergunta do usuário"""
    if not PRODUTOS:
        return []

    pergunta_lower = pergunta_usuario.lower()
    produtos_encontrados = []

    # Palavras comuns para ignorar
    stopwords = ['qual', 'o', 'a', 'os', 'as', 'um', 'uma', 'para', 'por', 'com',
                 'sem', 'sobre', 'de', 'da', 'do', 'das', 'dos', 'me', 'fale', 'diga',
                 'informação', 'informacoes', 'sobre', 'preço', 'preco', 'olá', 'ola',
                 'oi', 'bom', 'boa', 'dia', 'tarde', 'noite', 'tudo', 'bem', 'gostaria',
                 'quero', 'preciso', 'busco', 'procuro', 'ver', 'ter', 'comprar']

    # Palavras que indicam consulta genérica ao catálogo
    gatilhos_genericos = ['celular', 'smartphone', 'telefone', 'aparelho', 'modelo',
                          'opção', 'opcao', 'catalogo', 'catálogo', 'produto', 'disponível',
                          'disponivel', 'estoque', 'vende', 'tem', 'lista']

    # Extrai palavras-chave
    palavras = pergunta_lower.split()
    palavras_chave = [p for p in palavras if p not in stopwords and len(p) > 2]

    print(f"\n🔍 Buscando: {pergunta_usuario}")
    print(f"📝 Palavras-chave: {palavras_chave}")

    # Se a pergunta for genérica (ex: "quero um celular"), retorna os primeiros produtos
    eh_generica = any(g in pergunta_lower for g in gatilhos_genericos)
    nenhuma_chave_especifica = all(p in stopwords or p in gatilhos_genericos for p in palavras)

    if eh_generica and nenhuma_chave_especifica:
        print("   ℹ️ Consulta genérica — retornando catálogo completo")
        return PRODUTOS[:limite]

    for produto in PRODUTOS:
        if produto.get('preco') is None:
            continue

        relevancia = 0
        nome_completo = produto.get('nome', '').lower()

        for palavra in palavras_chave:
            if palavra in nome_completo:
                relevancia += 10 if len(palavra) > 3 else 5
                print(f"   ✓ Match: '{palavra}' em {produto.get('nome')}")

        # Busca por marca específica
        for marca in ['samsung', 'apple', 'motorola', 'xiaomi', 'realme', 'iphone', 'redmi', 'poco', 'moto']:
            if marca in pergunta_lower and marca in nome_completo:
                relevancia += 8
                numeros = re.findall(r'\d+[a-z]*', pergunta_lower)
                for num in numeros:
                    if num in nome_completo:
                        relevancia += 5

        if relevancia > 0:
            produtos_encontrados.append((relevancia, produto))

    # Se não achou nada por nome mas a pergunta tem algum conteúdo, retorna catálogo
    if not produtos_encontrados and palavras_chave:
        print("   ℹ️ Sem match específico — retornando catálogo completo")
        return PRODUTOS[:limite]

    produtos_encontrados.sort(key=lambda x: x[0], reverse=True)
    resultados = [p for _, p in produtos_encontrados[:limite]]

    print(f"📊 Encontrados: {len(resultados)} produtos")
    if resultados:
        print(f"🏆 Top resultado: {resultados[0].get('nome')}")

    return resultados

def formatar_produtos_para_prompt(produtos):
    """Formata os produtos para enviar à IA"""
    if not produtos:
        return "Nenhum produto encontrado no catálogo para esta consulta."
    
    texto = "📱 PRODUTOS ENCONTRADOS NO CATÁLOGO:\n\n"
    for i, produto in enumerate(produtos, 1):
        texto += f"{i}. {produto.get('nome', 'N/A')}\n"
        texto += f"   - Armazenamento: {produto.get('memoria', 'N/A')}\n"
        texto += f"   - RAM: {produto.get('ram', 'N/A')}\n"
        texto += f"   - Preço: R$ {produto.get('preco', 0):.2f}\n"
        if produto.get('promocao') and produto.get('preco_antigo'):
            texto += f"   - PROMOÇÃO: De R$ {produto.get('preco_antigo'):.2f} por R$ {produto.get('preco'):.2f}\n"
        texto += f"   - Tipo: {produto.get('tipo', 'N/A')}\n"
        texto += f"   - Cores: {', '.join(produto.get('cores', []))}\n\n"
    return texto

# ==================================================
# ROTAS - CORRIGIDAS!
# ==================================================

# Rota GET para verificar status (mantida)
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "assistant": "BINHO IA",
        "produtos_carregados": len(PRODUTOS),
        "arquivo_json": PRODUTOS_PATH
    })

# Rota POST na RAIZ (é o que seu front-end usa!)
@app.route("/", methods=["POST"])
def chat_root():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"success": False, "message": "Nenhum dado enviado ou Content-Type inválido."}), 400

        user_message = data.get("message", "").strip()
        if not user_message:
            return jsonify({"success": False, "message": "Mensagem vazia."}), 400

        if not PRODUTOS:
            return jsonify({"success": False, "message": "Catálogo de produtos indisponível. Verifique o arquivo produtos.json."}), 503

        print(f"\n{'='*50}")
        print(f"📨 Cliente: {user_message}")
        print(f"{'='*50}")

        # Buscar produtos
        produtos_relevantes = buscar_produtos_relevantes(user_message, limite=5)
        produtos_texto = formatar_produtos_para_prompt(produtos_relevantes)
        
        # Histórico da conversa (se enviado pelo frontend)
        historico = data.get("historico", [])
        historico_texto = ""
        if historico:
            historico_texto = "HISTÓRICO RECENTE DA CONVERSA:\n"
            for msg in historico[-6:]:  # últimas 6 mensagens
                papel = "Cliente" if msg.get("role") == "user" else "Binho IA"
                historico_texto += f"{papel}: {msg.get('content', '')}\n"
            historico_texto += "\n"

        # Prompt do sistema
        system_prompt = f"""Você é BINHO IA, assistente de vendas da Binho Celulares (binhocelulares.com.br).

REGRAS DE COMPORTAMENTO:
- Seja DIRETO e CONCISO. Sem enrolação.
- NUNCA comece a resposta com "Olá", "Oi", "Claro!", "Com certeza!", "Ótima escolha!" ou qualquer saudação/afirmação genérica.
- NUNCA repita frases que já usou antes no histórico da conversa.
- NUNCA invente preços, modelos ou especificações — use APENAS os dados dos produtos listados.
- Se o produto não estiver no catálogo, diga claramente que não temos esse item.
- Use no máximo 3-4 linhas por resposta, salvo quando listar múltiplos produtos.
- Ao listar produtos, use formato limpo: nome, preço, memória. Sem repetir "o produto X tem...".
- Fale como um vendedor jovem e experiente, não como um robô corporativo.
- Mencione o site apenas se o cliente perguntar onde comprar(binhocelulares.com.br).

{historico_texto}{produtos_texto}

PERGUNTA DO CLIENTE: {user_message}

RESPOSTA (direta, sem saudação):"""

        full_prompt = system_prompt

        # Chamar Gemini
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=full_prompt
        )

        # Extrai texto da resposta com segurança
        resposta_texto = ""
        if response and response.candidates:
            candidate = response.candidates[0]
            if candidate.content and candidate.content.parts:
                resposta_texto = "".join(part.text for part in candidate.content.parts if hasattr(part, "text")).strip()

        if not resposta_texto:
            return jsonify({"success": False, "message": "A IA não retornou uma resposta válida. Tente novamente."}), 502

        # Pós-processamento: remove saudações genéricas no início da resposta
        import re as _re
        saudacoes_padrao = [
            r'^(olá|ola|oi|hey|e aí|e ai)[,!]?\s*',
            r'^(claro|claro que sim|com certeza|certamente|absolutamente)[,!]?\s*',
            r'^(ótima|otima|boa|excelente)\s+(pergunta|escolha|opção|opcao)[,!]?\s*',
            r'^(pois não|pois nao|pode deixar)[,!]?\s*',
        ]
        for padrao in saudacoes_padrao:
            resposta_texto = _re.sub(padrao, '', resposta_texto, flags=_re.IGNORECASE).strip()

        # Garante que a primeira letra seja maiúscula
        if resposta_texto:
            resposta_texto = resposta_texto[0].upper() + resposta_texto[1:]

        print(f"✅ Resposta enviada ao cliente")
        return jsonify({"success": True, "response": resposta_texto})

    except Exception as error:
        print(f"❌ Erro: {str(error)}")
        return jsonify({"success": False, "error": str(error)}), 500

# Rota /chat também funciona (para compatibilidade)
@app.route("/chat", methods=["POST"])
def chat_alt():
    return chat_root()

# Rota para listar produtos (útil para debug)
@app.route("/produtos", methods=["GET"])
def listar_produtos():
    return jsonify({
        "total": len(PRODUTOS),
        "produtos": [{"nome": p.get('nome'), "preco": p.get('preco')} for p in PRODUTOS]
    })

# ==================================================
# INICIAR SERVIDOR
# ==================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 BINHO IA BACKEND")
    print("="*60)
    print(f"📂 Pasta do app: {BACKEND_DIR}")
    print(f"📦 Arquivo JSON: {PRODUTOS_PATH}")
    print(f"📊 Produtos: {len(PRODUTOS)}")
    print("🌐 Servidor: https://chat-bot-back-1.onrender.com")
    print("📡 Rotas disponíveis:")
    print("   GET  /          - Status do servidor")
    print("   POST /          - Chat (principal)")
    print("   POST /chat      - Chat (alternativo)")
    print("   GET  /produtos  - Listar produtos")
    print("="*60 + "\n")
    
    DEBUG_MODE = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=DEBUG_MODE)