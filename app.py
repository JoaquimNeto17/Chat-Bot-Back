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

# Configurar encoding do console para Windows (Mantido para desenvolvimento local)
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

# Procura o JSON na mesma pasta do app.py
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUTOS_PATH = os.path.join(BACKEND_DIR, 'produtos.json')

print(f"📂 Procurando produtos.json em: {PRODUTOS_PATH}")

# Chave da API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configurar cliente Gemini com verificação segura
client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    print("⚠️ GEMINI_API_KEY não encontrada no ambiente. Certifique-se de configurá-la no Render.")

# Flask
app = Flask(__name__)
# CORS configurado explicitamente para permitir qualquer origem em produção
CORS(app, resources={r"/*": {"origins": "*"}})

# ==================================================
# CARREGAR PRODUTOS DO JSON
# ==================================================

def carregar_produtos():
    """Carrega a lista de produtos do arquivo produtos.json"""
    try:
        with open(PRODUTOS_PATH, 'r', encoding='utf-8') as f:
            dados = json.load(f)

        if isinstance(dados, list):
            raw = dados
        elif isinstance(dados, dict):
            raw = next((v for v in dados.values() if isinstance(v, list)), [])
        else:
            raw = []

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
        return produtos
    except FileNotFoundError:
        print(f"❌ ERRO: Arquivo não encontrado em: {PRODUTOS_PATH}")
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

    stopwords = ['qual', 'o', 'a', 'os', 'as', 'um', 'uma', 'para', 'por', 'com',
                 'sem', 'sobre', 'de', 'da', 'do', 'das', 'dos', 'me', 'fale', 'diga',
                 'informação', 'informacoes', 'sobre', 'preço', 'preco', 'olá', 'ola',
                 'oi', 'bom', 'boa', 'dia', 'tarde', 'noite', 'tudo', 'bem', 'gostaria',
                 'quero', 'preciso', 'busco', 'procuro', 'ver', 'ter', 'comprar']

    gatilhos_genericos = ['celular', 'smartphone', 'telefone', 'aparelho', 'modelo',
                          'opção', 'opcao', 'catalogo', 'catálogo', 'produto', 'disponível',
                          'disponivel', 'estoque', 'vende', 'tem', 'lista']

    palavras = pergunta_lower.split()
    palavras_chave = [p for p in palavras if p not in stopwords and len(p) > 2]

    eh_generica = any(g in pergunta_lower for g in gatilhos_genericos)
    nenhuma_chave_especifica = all(p in stopwords or p in gatilhos_genericos for p in palavras)

    if eh_generica and nenhuma_chave_especifica:
        return PRODUTOS[:limite]

    for produto in PRODUTOS:
        if produto.get('preco') is None:
            continue

        relevancia = 0
        nome_completo = produto.get('nome', '').lower()

        for palavra in palavras_chave:
            if palavra in nome_completo:
                relevancia += 10 if len(palavra) > 3 else 5

        for marca in ['samsung', 'apple', 'motorola', 'xiaomi', 'realme', 'iphone', 'redmi', 'poco', 'moto']:
            if marca in pergunta_lower and marca in nome_completo:
                relevancia += 8
                numeros = re.findall(r'\d+[a-z]*', pergunta_lower)
                for num in numeros:
                    if num in nome_completo:
                        relevancia += 5

        if relevancia > 0:
            produtos_encontrados.append((relevancia, produto))

    if not produtos_encontrados and palavras_chave:
        return PRODUTOS[:limite]

    produtos_encontrados.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in produtos_encontrados[:limite]]

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
# ROTA PRINCIPAL
# ==================================================

@app.route("/chat", methods=["POST"])
def chat():
    global client
    try:
        # Recarrega a lista se ela estiver vazia por erro de concorrência inicial
        global PRODUTOS
        if not PRODUTOS:
            PRODUTOS = carregar_produtos()

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"success": False, "message": "Nenhum dado enviado ou Content-Type inválido."}), 400

        user_message = data.get("message", "").strip()
        if not user_message:
            return jsonify({"success": False, "message": "Mensagem vazia."}), 400

        if not PRODUTOS:
            return jsonify({"success": False, "message": "Catálogo de produtos indisponível."}), 503

        # Inicialização tardia do client caso a env tenha sido injetada depois
        if not client:
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key:
                client = genai.Client(api_key=api_key)
            else:
                return jsonify({"success": False, "message": "Configuração da API Key ausente no servidor."}), 500

        # Buscar produtos
        produtos_relevantes = buscar_produtos_relevantes(user_message, limite=5)
        produtos_texto = formatar_produtos_para_prompt(produtos_relevantes)
        
        # Histórico da conversa
        historico = data.get("historico", [])
        historico_texto = ""
        if historico:
            historico_texto = "HISTÓRICO RECENTE DA CONVERSA:\n"
            for msg in historico[-6:]:
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

        # Chamar Gemini
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=system_prompt
        )

        resposta_texto = ""
        if response and response.candidates:
            candidate = response.candidates[0]
            if candidate.content and candidate.content.parts:
                resposta_texto = "".join(part.text for part in candidate.content.parts if hasattr(part, "text")).strip()

        if not resposta_texto:
            return jsonify({"success": False, "message": "A IA não retornou uma resposta válida."}), 502

        # Pós-processamento de saudações
        saudacoes_padrao = [
            r'^(olá|ola|oi|hey|e aí|e ai)[,!]?\s*',
            r'^(claro|claro que sim|com certeza|certamente|absolutamente)[,!]?\s*',
            r'^(ótima|otima|boa|excelente)\s+(pergunta|escolha|opção|opcao)[,!]?\s*',
            r'^(pois não|pois nao|pode deixar)[,!]?\s*',
        ]
        for padrao in saudacoes_padrao:
            resposta_texto = re.sub(padrao, '', resposta_texto, flags=re.IGNORECASE).strip()

        if resposta_texto:
            resposta_texto = resposta_texto[0].upper() + resposta_texto[1:]

        return jsonify({"success": True, "response": resposta_texto})

    except Exception as error:
        print(f"❌ Erro: {str(error)}")
        return jsonify({"success": False, "error": str(error)}), 500

# ==================================================
# ROTAS AUXILIARES
# ==================================================

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "assistant": "BINHO IA",
        "produtos_carregados": len(PRODUTOS)
    })

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
    port = int(os.environ.get("PORT", 5000))
    # Em produção no Render, debug deve ser False por padrão
    app.run(host="0.0.0.0", port=port, debug=False)