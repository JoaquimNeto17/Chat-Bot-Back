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
# FUNÇÃO DE BUSCA ALTERADA E CORRIGIDA
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

    # CORREÇÃO: Se for apenas uma saudação ("olá") ou texto sem palavras-chave, 
    # retornamos os primeiros produtos para dar contexto à IA, evitando que o prompt receba um texto vazio.
    if (eh_generica and nenhuma_chave_especifica) or not palavras_chave:
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

    # Fallback se buscou algo específico mas não encontrou nada no catálogo
    if not produtos_encontrados:
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

        # Buscar produtos relevantes
        produtos_relevantes = buscar_produtos_relevantes(user_message, limite=5)
        produtos_texto = formatar_produtos_para_prompt(produtos_relevantes)
        
        # Histórico da conversa
        historico = data.get("historico", [])
        historico_texto = ""
        if historico:
            historico_texto = "HISTÓRICO RECENTE DA CONVERSA:\n"
            for msg in historico[-6:]:
                papel = "Cliente" if msg.get("role") == "user" else "Assistente"
                historico_texto += f"{papel}: {msg.get('content', '')}\n"
            historico_texto += "\n"

        # PROMPT DO SISTEMA: PERSONALIDADE CARISMÁTICA, SEM NOME E SEM SE TITULAR DONO
        system_prompt = f"""Você é o assistente virtual oficial da loja Binho Celulares (binhocelulares.com.br). Seu objetivo principal é atender o cliente de forma ultra simpática, prestativa, criar conexão imediata e VENDER os aparelhos do catálogo.

REGRAS CRÍTICAS DE COMPORTAMENTO:
- Identidade Restrita: NUNCA diga seu nome (não use "Binho IA" ou "Binho") e NUNCA se auto-intitule como "dono da loja", "proprietário", "patrão" ou termos similares. Fale sempre em nome da loja (ex: "Temos aqui na loja...", "Consigo esse preço para você...").
- Personalidade: Seja muito carismático, entusiasmado, apaixonado por tecnologia e focado em fechar negócios. Use uma linguagem natural, calorosa e vendedora.
- Saudações: Responda de forma receptiva e amigável a cumprimentos ("Olá", "Oi", "Tudo bem?") e encaminhe o papo para entender qual celular o cliente deseja.
- Foco Total em Smartphones: Você APENAS conversa sobre celulares, acessórios, tecnologia mobile e os produtos em estoque. Se o cliente desviar de assunto, mude o foco de volta para celulares de forma sutil e inteligente.
- Honestidade Absoluta: Use APENAS as especificações, preços e modelos que constam estritamente no catálogo abaixo. Nunca invente dados. Se não houver o item exato pedido, recomende calorosamente o celular mais parecido do estoque.
- Listagem Inteligente: Ao listar os aparelhos, apresente os dados de forma limpa e muito atraente, ressaltando os pontos fortes deles para cativar o cliente.
- Call to Action: Sempre estimule o cliente a tomar uma ação de compra ou a acessar o site binhocelulares.com.br para fechar o pedido.

{historico_texto}{produtos_texto}

PERGUNTA DO CLIENTE: {user_message}

RESPOSTA (Carismática, focada em conversão, use emojis celulares, SEM se chamar de dono e SEM falar nome próprio):"""

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

        # CORREÇÃO: O bloco antigo de remoção rígida de saudações por Regex foi deletado
        # para permitir que a IA envie "Olá", "Oi" ou expressões calorosas naturalmente.
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
        "assistant": "ATIVO",
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
    app.run(host="0.0.0.0", port=port, debug=False)