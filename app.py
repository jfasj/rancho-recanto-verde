
import os
import re
import sqlite3
import hashlib
import xml.etree.ElementTree as ET

try:
    from twilio.rest import Client
except Exception:
    Client = None
from datetime import datetime, date, timedelta
from urllib.parse import quote
from io import BytesIO

import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


# =========================================================
# CONFIGURAÇÃO
# =========================================================

st.set_page_config(
    page_title="Rancho Recanto Verde",
    layout="wide",
    initial_sidebar_state="expanded"
)

LOGO = "logo.png"
DB = "rancho.db"

conn = sqlite3.connect(DB, check_same_thread=False)
c = conn.cursor()


# =========================================================
# BANCO DE DADOS
# =========================================================

TABELAS = [
    "animais",
    "farmacia",
    "sanitario",
    "tratamentos",
    "pesagens",
    "doadoras",
    "receptoras",
    "vendas",
    "recebimentos",
    "funcionarios",
    "alertas_whatsapp",
    "medicacoes_agendadas",
    "compras_nfe",
    "abqm_consultas",
    "usuarios",
]

for tabela in TABELAS:
    c.execute(f"CREATE TABLE IF NOT EXISTS {tabela} (id INTEGER PRIMARY KEY AUTOINCREMENT)")


def add_col(tabela, coluna, tipo="TEXT"):
    cols = pd.read_sql_query(f"PRAGMA table_info({tabela})", conn)["name"].tolist()
    if coluna not in cols:
        c.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
        
for col in [
    "quantidade_compra", "unidade_compra", "volume_por_unidade",
    "unidade_controle", "estoque_convertido", "estoque_min_controle",
    "preco_por_controle"
]:
    add_col("farmacia", col)

conn.commit()


for col in [
    "nome", "tipo", "especie", "raca", "sexo", "nascimento", "cor",
    "responsavel", "cpf", "telefone", "local", "microchip", "status",
    "registro_abqm", "nome_oficial_abqm", "pai_abqm", "mae_abqm",
    "criador_abqm", "proprietario_abqm", "link_abqm", "obs_abqm",
    "obs"
]:
    add_col("animais", col)

for col in [
    "medicamento", "categoria", "quantidade", "estoque_min", "unidade",
    "preco", "validade", "fornecedor", "obs"
]:
    add_col("farmacia", col)

for col in [
    "animal", "tipo", "procedimento", "produto", "data_aplicacao",
    "proxima_dose", "quantidade_usada", "unidade", "preco_unitario",
    "custo_total", "responsavel", "obs"
]:
    add_col("sanitario", col)

for col in [
    "animal", "tipo", "data", "motivo", "diagnostico", "tratamento",
    "medicamento", "quantidade_usada", "unidade", "dosagem",
    "preco_unitario", "custo_total", "veterinario", "retorno",
    "funcionario_responsavel", "telefone_funcionario",
    "data_hora_medicacao", "gerar_alerta_whatsapp", "obs"
]:
    add_col("tratamentos", col)

for col in ["animal", "tipo", "data_pesagem", "peso", "obs"]:
    add_col("pesagens", col)

for col in [
    "egua_doadora", "garanhao", "data_inseminacao", "protocolo",
    "dosagens", "data_prevista_lavagem", "data_lavagem",
    "resultado_lavagem", "embrioes_coletados", "status", "obs"
]:
    add_col("doadoras", col)

for col in [
    "receptora", "egua_doadora", "garanhao", "cruzamento",
    "data_transferencia", "dosagens", "protocolo", "previsao_parto",
    "confirmacao_prenhez", "status", "obs"
]:
    add_col("receptoras", col)

for col in [
    "animal", "tipo", "data_venda", "valor_negociado", "desconto",
    "valor_final", "forma_pagamento", "parcelas", "status_venda",
    "comprador_nome", "comprador_cpf_cnpj", "comprador_telefone",
    "comprador_email", "comprador_endereco", "obs"
]:
    add_col("vendas", col)

for col in [
    "venda_id", "animal", "comprador", "parcela", "vencimento",
    "valor", "data_pagamento", "status", "obs"
]:
    add_col("recebimentos", col)

for col in ["nome", "senha_hash", "perfil", "permissoes", "ativo"]:
    add_col("usuarios", col)

for col in [
    "nome", "cpf", "rg", "telefone", "email", "endereco", "cargo",
    "setor", "salario", "data_admissao", "status", "documentos", "obs"
]:
    add_col("funcionarios", col)

for col in [
    "funcionario", "telefone", "tipo_alerta", "mensagem", "data_envio",
    "status", "sid_twilio", "erro_twilio", "obs"
]:
    add_col("alertas_whatsapp", col)

for col in [
    "animal", "tipo_animal", "medicamento", "dosagem", "data_hora",
    "funcionario", "telefone", "mensagem", "status", "alerta_gerado",
    "data_alerta", "sid_twilio", "erro_twilio", "obs"
]:
    add_col("medicacoes_agendadas", col)

for col in [
    "chave_nfe", "numero_nfe", "data_emissao", "fornecedor",
    "cnpj_fornecedor", "produto", "ncm", "quantidade", "unidade",
    "valor_unitario", "valor_total", "data_importacao"
]:
    add_col("compras_nfe", col)

for col in [
    "animal", "registro_abqm", "nome_oficial", "pai", "mae",
    "pelagem", "nascimento", "criador", "proprietario",
    "link_consulta", "observacoes", "data_cadastro"
]:
    add_col("abqm_consultas", col)

conn.commit()


# =========================================================
# USUÁRIOS / SEGURANÇA
# =========================================================

TODAS_PERMISSOES = [
    "Dashboard",
    "Cadastrar Animal",
    "Animais por Tipo",
    "Pesagem / Evolução",
    "Controle Sanitário",
    "Farmácia",
    "Veterinário / Tratamentos",
    "Reprodução / Embriões",
    "Vendas de Animais",
    "Relatórios / Gráficos",
    "Gerar PDF",
    "Admin / Usuários",
    "Funcionários",
    "Alertas WhatsApp",
    "Importar NF-e / XML",
    "Consulta ABQM",
]


PERFIS = {
    "Administrador": TODAS_PERMISSOES,
    "Veterinário": [
        "Dashboard",
        "Animais por Tipo",
        "Controle Sanitário",
        "Veterinário / Tratamentos",
        "Reprodução / Embriões",
        "Alertas WhatsApp",
        "Gerar PDF",
    ],
    "Financeiro": [
        "Dashboard",
        "Vendas de Animais",
        "Importar NF-e / XML",
        "Consulta ABQM",
        "Relatórios / Gráficos",
        "Alertas WhatsApp",
        "Gerar PDF",
    ],
    "Operacional": [
        "Dashboard",
        "Cadastrar Animal",
        "Animais por Tipo",
        "Pesagem / Evolução",
        "Controle Sanitário",
        "Importar NF-e / XML",
        "Consulta ABQM",
        "Funcionários",
        "Alertas WhatsApp",
    ],
}


def hash_senha(senha):
    return hashlib.sha256(str(senha).encode("utf-8")).hexdigest()


def criar_admin_padrao():
    usuarios = pd.read_sql_query("SELECT * FROM usuarios WHERE nome IS NOT NULL AND nome != ''", conn)
    if usuarios.empty:
        c.execute("""
            INSERT INTO usuarios (nome, senha_hash, perfil, permissoes, ativo)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "admin",
            hash_senha("1234"),
            "Administrador",
            "|".join(TODAS_PERMISSOES),
            "Sim"
        ))
        conn.commit()



def atualizar_admin_permissoes():
    c.execute("""
        UPDATE usuarios
        SET permissoes = ?, perfil = ?, ativo = ?
        WHERE nome = ?
    """, (
        "|".join(TODAS_PERMISSOES),
        "Administrador",
        "Sim",
        "admin"
    ))
    conn.commit()


def carregar_usuario(nome):
    df = pd.read_sql_query(
        "SELECT * FROM usuarios WHERE nome = ? AND ativo = 'Sim'",
        conn,
        params=(nome,)
    )
    if df.empty:
        return None
    return df.iloc[0].to_dict()


def usuario_tem_permissao(pagina):
    if "usuario" not in st.session_state:
        return False
    permissoes = st.session_state.usuario.get("permissoes", "")
    return pagina in permissoes.split("|")


criar_admin_padrao()
atualizar_admin_permissoes()


# =========================================================
# VISUAL PREMIUM
# =========================================================

st.markdown("""
<style>
:root {
    --bg: #07111f;
    --panel: #101d2c;
    --panel2: #142235;
    --gold: #d4af37;
    --gold2: #b8860b;
    --text: #f8fafc;
    --muted: #cbd5e1;
    --line: rgba(212,175,55,0.25);
    --red: #ef4444;
    --green: #22c55e;
}

.stApp {
    background:
        radial-gradient(circle at top center, rgba(212,175,55,0.07), transparent 35%),
        linear-gradient(135deg, #07111f 0%, #0b1320 55%, #07111f 100%);
    color: var(--text);
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #081526 0%, #101827 100%);
    border-right: 1px solid rgba(212,175,55,0.35);
}

[data-testid="stSidebar"] * {
    color: #f8fafc;
}

h1, h2, h3 {
    color: var(--text);
}

label, p, span {
    color: var(--text);
}

hr {
    border: none;
    border-top: 1px solid var(--line);
}

div[data-testid="stMetric"] {
    background: linear-gradient(135deg, rgba(21,33,52,0.98), rgba(13,25,41,0.98));
    border: 1px solid rgba(212,175,55,0.16);
    border-radius: 18px;
    padding: 18px;
    box-shadow: 0 14px 36px rgba(0,0,0,0.28);
}

div[data-testid="stMetricLabel"] {
    color: #cbd5e1 !important;
    font-size: 0.88rem;
}

div[data-testid="stMetricValue"] {
    color: #ffffff !important;
    font-weight: 800;
}

.stButton button,
.stDownloadButton button {
    background: linear-gradient(135deg, #b8860b, #d4af37);
    color: #07111f !important;
    border-radius: 12px;
    font-weight: 800;
    border: none;
    padding: 0.65rem 1rem;
}

.stButton button:hover,
.stDownloadButton button:hover {
    background: linear-gradient(135deg, #d4af37, #f4d36a);
    color: #07111f !important;
}

.card {
    background: linear-gradient(135deg, rgba(20,34,53,0.98), rgba(13,26,42,0.98));
    border: 1px solid rgba(212,175,55,0.16);
    border-radius: 18px;
    padding: 18px;
    box-shadow: 0 14px 36px rgba(0,0,0,0.28);
    min-height: 110px;
}

.card-title {
    font-size: 0.82rem;
    color: #cbd5e1;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

.card-value {
    font-size: 1.85rem;
    font-weight: 900;
    color: #fff;
    margin-top: 5px;
}

.card-sub {
    font-size: 0.88rem;
    color: #cbd5e1;
    margin-top: 5px;
}

.icon-box {
    width: 52px;
    height: 52px;
    border-radius: 14px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 1.8rem;
    margin-right: 12px;
    background: linear-gradient(135deg, rgba(212,175,55,0.45), rgba(184,134,11,0.25));
    box-shadow: inset 0 0 18px rgba(255,255,255,0.07);
}

.topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: rgba(10,22,36,0.86);
    border: 1px solid rgba(212,175,55,0.18);
    border-radius: 18px;
    padding: 12px 16px;
    margin-bottom: 18px;
}

.topbar-title {
    font-weight: 900;
    color: #fff;
    font-size: 1.05rem;
}

.topbar-menu {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

.pill {
    border: 1px solid rgba(212,175,55,0.25);
    border-radius: 999px;
    padding: 8px 12px;
    background: rgba(212,175,55,0.08);
    color: #f8fafc;
    font-weight: 700;
}

.section-title {
    font-size: 1.45rem;
    font-weight: 900;
    margin: 10px 0 4px 0;
}

.section-subtitle {
    color: #cbd5e1;
    margin-bottom: 22px;
}

.alert-card {
    background: rgba(15, 28, 45, 0.96);
    border: 1px solid rgba(212,175,55,0.16);
    border-radius: 18px;
    padding: 16px;
    min-height: 250px;
}

.footer {
    text-align: center;
    color: #cbd5e1;
    padding: 20px 0 5px 0;
    font-size: 0.9rem;
}

[data-testid="stDataFrame"] {
    border-radius: 16px;
    overflow: hidden;
}

div[data-baseweb="select"] > div {
    background-color: rgba(20,34,53,0.98);
    border-radius: 12px;
    border-color: rgba(212,175,55,0.25);
}

input, textarea {
    background-color: rgba(20,34,53,0.98) !important;
    color: #f8fafc !important;
}


[data-testid="stSidebar"] [role="radiogroup"] label {
    background: rgba(15, 28, 45, 0.72);
    border: 1px solid rgba(212,175,55,0.12);
    border-radius: 12px;
    padding: 8px 10px;
    margin: 4px 0;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {
    background: rgba(212,175,55,0.16);
    border-color: rgba(212,175,55,0.35);
}


/* Botões do menu superior */
div[data-testid="column"] .stButton button {
    min-height: 56px;
    font-size: 1.08rem;
    border-radius: 16px;
    border: 1px solid rgba(212,175,55,0.28);
    background: linear-gradient(135deg, rgba(21,33,52,0.98), rgba(13,26,42,0.98));
    color: #f8fafc !important;
    box-shadow: 0 10px 28px rgba(0,0,0,0.22);
}
div[data-testid="column"] .stButton button:hover {
    background: linear-gradient(135deg, #b8860b, #d4af37);
    color: #07111f !important;
    border-color: rgba(212,175,55,0.9);
}


/* HOME ESTILO APP PROFISSIONAL */
.app-grid-card {
    background: linear-gradient(135deg, rgba(20,34,53,0.98), rgba(10,22,36,0.98));
    border: 1px solid rgba(212,175,55,0.22);
    border-radius: 22px;
    padding: 22px;
    min-height: 145px;
    box-shadow: 0 16px 36px rgba(0,0,0,0.30);
    text-align: center;
    margin-bottom: 14px;
}
.app-grid-icon {
    font-size: 2.4rem;
    margin-bottom: 8px;
}
.app-grid-title {
    font-size: 1.05rem;
    font-weight: 900;
    color: #ffffff;
}
.app-grid-subtitle {
    font-size: 0.86rem;
    color: #cbd5e1;
    margin-top: 5px;
}
.quick-title {
    font-size: 1.55rem;
    font-weight: 900;
    color: #ffffff;
    margin-bottom: 2px;
}
.quick-subtitle {
    color: #cbd5e1;
    margin-bottom: 22px;
}

</style>
""", unsafe_allow_html=True)


# =========================================================
# FUNÇÕES
# =========================================================

tipos = ["Equino", "Canino", "Bovino", "Ovino", "Caprino", "Suíno", "Ave", "Felino", "Outro"]


def br_data(data_obj):
    try:
        return data_obj.strftime("%d/%m/%Y")
    except Exception:
        return ""


def parse_data(txt):
    try:
        return datetime.strptime(str(txt), "%d/%m/%Y").date()
    except Exception:
        return None


def moeda(valor):
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def listar_animais(somente_ativos=False):
    df = pd.read_sql_query("SELECT * FROM animais WHERE nome IS NOT NULL AND nome != ''", conn)
    if somente_ativos and not df.empty and "status" in df.columns:
        df = df[df["status"].fillna("").str.upper() != "VENDIDO"]
    return df


def listar_farmacia():
    return pd.read_sql_query("SELECT * FROM farmacia WHERE medicamento IS NOT NULL AND medicamento != ''", conn)


def status_data(data_txt, dias_alerta=30):
    d = parse_data(data_txt)
    if not d:
        return "DATA INVÁLIDA"
    dias = (d - date.today()).days
    if dias < 0:
        return "VENCIDO"
    if dias <= dias_alerta:
        return "PRÓXIMO"
    return "OK"


def baixar_estoque(medicamento, quantidade_usada):
    med = pd.read_sql_query(
        "SELECT * FROM farmacia WHERE medicamento = ?",
        conn,
        params=(medicamento,)
    )

    if med.empty:
        return False, 0, 0, "Medicamento não encontrado na farmácia."

    row = med.iloc[0]

    try:
        quantidade_usada = float(quantidade_usada or 0)
    except Exception:
        quantidade_usada = 0

    unidade_controle = row.get("unidade_controle", "") or row.get("unidade", "")
    estoque_convertido = row.get("estoque_convertido", "")

    if estoque_convertido not in [None, ""]:
        estoque_atual = float(estoque_convertido or 0)
        preco_unitario = float(row.get("preco_por_controle", 0) or 0)

        if quantidade_usada > estoque_atual:
            return False, estoque_atual, preco_unitario, f"Estoque insuficiente. Disponível: {estoque_atual} {unidade_controle}."

        novo_estoque = estoque_atual - quantidade_usada

        c.execute("""
            UPDATE farmacia
            SET estoque_convertido = ?
            WHERE medicamento = ?
        """, (str(novo_estoque), medicamento))

        conn.commit()
        return True, novo_estoque, preco_unitario, ""

    estoque_atual = float(row["quantidade"] or 0)
    preco_unitario = float(row["preco"] or 0)

    if quantidade_usada > estoque_atual:
        return False, estoque_atual, preco_unitario, "Estoque insuficiente."

    novo_estoque = estoque_atual - quantidade_usada

    c.execute("""
        UPDATE farmacia
        SET quantidade = ?
        WHERE medicamento = ?
    """, (str(novo_estoque), medicamento))

    conn.commit()
    return True, novo_estoque, preco_unitario, ""



def gerar_excel(df):
    buffer = BytesIO()
    df.to_excel(buffer, index=False)
    return buffer.getvalue()


def card(icon, title, value, subtitle="", accent="#d4af37"):
    st.markdown(
        f"""
        <div class="card">
            <div style="display:flex; align-items:center;">
                <div class="icon-box" style="background:linear-gradient(135deg, {accent}, rgba(255,255,255,0.08));">{icon}</div>
                <div>
                    <div class="card-title">{title}</div>
                    <div class="card-value">{value}</div>
                    <div class="card-sub">{subtitle}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def titulo_pagina(titulo, subtitulo=""):
    st.markdown(
        f"""
        <div class="section-title">{titulo}</div>
        <div class="section-subtitle">{subtitulo}</div>
        """,
        unsafe_allow_html=True
    )


# =========================================================
# LOGIN
# =========================================================

if "logado" not in st.session_state:
    st.session_state.logado = False

if not st.session_state.logado:
    st.markdown("<br><br>", unsafe_allow_html=True)

    col_login1, col_login2, col_login3 = st.columns([1, 1.2, 1])

    with col_login2:
        if os.path.exists(LOGO):
            st.image(LOGO, use_container_width=True)

        st.markdown("### 🔐 Acesso ao Sistema")
        nome_login = st.text_input("Usuário")
        senha_login = st.text_input("Senha", type="password")

        if st.button("Entrar", use_container_width=True):
            usuario = carregar_usuario(nome_login)

            if usuario and usuario["senha_hash"] == hash_senha(senha_login):
                st.session_state.logado = True
                st.session_state.usuario = usuario
                st.session_state.pagina_atual = "Dashboard"
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")

        st.info("Acesso inicial: usuário **admin** | senha **1234**. Altere depois em Admin / Usuários.")

    st.stop()


def topbar():
    st.markdown(
        """
        <div class="topbar">
            <div class="topbar-title">Rancho Recanto Verde</div>
            <div class="topbar-menu">
                <span class="pill">🏠 Dashboard</span>
                <span class="pill">📊 Relatórios / Gráficos</span>
                <span class="pill">📋 Menus</span>
                <span class="pill">🔔 Alertas</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )



def limpar_numero(valor):
    try:
        return float(str(valor).replace(",", "."))
    except Exception:
        return 0.0


def get_text_xml(elemento, caminho, ns):
    encontrado = elemento.find(caminho, ns)
    return encontrado.text.strip() if encontrado is not None and encontrado.text else ""


def link_consulta_abqm(termo=""):
    # Página oficial de consulta ABQM. A consulta exige login no site.
    base = "https://consulta.abqm.com.br/"
    return base


def ler_xml_nfe(xml_bytes):
    """
    Lê XML de NF-e e retorna dados básicos da nota e lista de produtos.
    Funciona com XML autorizado contendo nfeProc/NFe/infNFe.
    """
    root = ET.fromstring(xml_bytes)

    ns = {"nfe": "http://www.portalfiscal.inf.br/nfe"}

    inf = root.find(".//nfe:infNFe", ns)
    if inf is None:
        inf = root.find(".//infNFe")

    if inf is None:
        raise ValueError("XML inválido ou não parece ser uma NF-e.")

    chave = str(inf.attrib.get("Id", "")).replace("NFe", "")

    ide = inf.find("nfe:ide", ns)
    emit = inf.find("nfe:emit", ns)

    numero = get_text_xml(ide, "nfe:nNF", ns) if ide is not None else ""
    data_emissao = get_text_xml(ide, "nfe:dhEmi", ns) if ide is not None else ""
    if data_emissao:
        data_emissao = data_emissao[:10]

    fornecedor = get_text_xml(emit, "nfe:xNome", ns) if emit is not None else ""
    cnpj = get_text_xml(emit, "nfe:CNPJ", ns) if emit is not None else ""

    produtos = []

    for det in inf.findall("nfe:det", ns):
        prod = det.find("nfe:prod", ns)
        if prod is None:
            continue

        nome = get_text_xml(prod, "nfe:xProd", ns)
        ncm = get_text_xml(prod, "nfe:NCM", ns)
        unidade = get_text_xml(prod, "nfe:uCom", ns)
        quantidade = limpar_numero(get_text_xml(prod, "nfe:qCom", ns))
        valor_unitario = limpar_numero(get_text_xml(prod, "nfe:vUnCom", ns))
        valor_total = limpar_numero(get_text_xml(prod, "nfe:vProd", ns))

        produtos.append({
            "produto": nome,
            "ncm": ncm,
            "quantidade": quantidade,
            "unidade": unidade,
            "valor_unitario": valor_unitario,
            "valor_total": valor_total,
            "fornecedor": fornecedor,
            "cnpj_fornecedor": cnpj,
            "numero_nfe": numero,
            "chave_nfe": chave,
            "data_emissao": data_emissao,
        })

    return {
        "chave_nfe": chave,
        "numero_nfe": numero,
        "data_emissao": data_emissao,
        "fornecedor": fornecedor,
        "cnpj_fornecedor": cnpj,
        "produtos": produtos,
    }



# =========================================================
# TWILIO / WHATSAPP PROFISSIONAL
# =========================================================

def get_secret_value(nome, padrao=""):
    try:
        if nome in st.secrets:
            return st.secrets[nome]
    except Exception:
        pass
    return os.environ.get(nome, padrao)


def twilio_configurado():
    sid = get_secret_value("TWILIO_ACCOUNT_SID")
    token = get_secret_value("TWILIO_AUTH_TOKEN")
    from_number = get_secret_value("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    return bool(sid and token and from_number and Client is not None)


def normalizar_whatsapp(numero):
    numero = str(numero or "")
    numero = numero.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if numero and not numero.startswith("55"):
        numero = "55" + numero
    return numero


def enviar_whatsapp_twilio(numero, mensagem):
    if Client is None:
        return False, "", "Biblioteca twilio não instalada. Inclua twilio no requirements.txt."

    sid = get_secret_value("TWILIO_ACCOUNT_SID")
    token = get_secret_value("TWILIO_AUTH_TOKEN")
    from_number = get_secret_value("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

    if not sid or not token:
        return False, "", "Credenciais Twilio não configuradas."

    numero = normalizar_whatsapp(numero)
    if not numero:
        return False, "", "Telefone do funcionário não informado."

    try:
        client = Client(sid, token)
        msg = client.messages.create(
            body=str(mensagem),
            from_=from_number,
            to=f"whatsapp:+{numero}"
        )
        return True, msg.sid, ""
    except Exception as e:
        return False, "", str(e)


def registrar_alerta_whatsapp(funcionario, telefone, tipo_alerta, mensagem, status, sid_twilio="", erro_twilio="", obs=""):
    c.execute("""
        INSERT INTO alertas_whatsapp
        (funcionario, telefone, tipo_alerta, mensagem, data_envio, status, sid_twilio, erro_twilio, obs)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        funcionario,
        telefone,
        tipo_alerta,
        mensagem,
        datetime.now().strftime("%d/%m/%Y %H:%M"),
        status,
        sid_twilio,
        erro_twilio,
        obs
    ))
    conn.commit()




# =========================================================
# CONVERSÃO DE FARMÁCIA — mL / L
# =========================================================

def extrair_volume_descricao(produto):
    """
    Lê a descrição do produto e tenta identificar volume.
    Exemplos:
    - BUSCOFIN INJ 50ML -> 50, mL
    - MERCEPTON INJ 100 ML -> 100, mL
    - SORO FISIOLOGICO 1L -> 1, L
    - RINGER LACTATO 500ML -> 500, mL
    Se não encontrar, retorna 1, unidade sugerida.
    """
    texto = str(produto or "").upper()
    texto = texto.replace(",", ".")

    # Litros: 1L, 1 L, 1LT, 1 LITRO
    m_litro = re.search(r"(\d+(?:\.\d+)?)\s*(L|LT|LITRO|LITROS)\b", texto)
    if m_litro:
        return float(m_litro.group(1)), "L"

    # Mililitros: 50ML, 50 ML, 100ML
    m_ml = re.search(r"(\d+(?:\.\d+)?)\s*(ML|M/L|MILILITRO|MILILITROS)\b", texto)
    if m_ml:
        return float(m_ml.group(1)), "mL"

    # Padrões muito comuns sem espaço estranho: 50ML colado em palavra
    m_ml_colado = re.search(r"(\d+(?:\.\d+)?)ML", texto)
    if m_ml_colado:
        return float(m_ml_colado.group(1)), "mL"

    # Se for soro sem volume, sugere litro, mas mantém volume 1 para ajuste
    if "SORO" in texto or "RINGER" in texto or "FISIOLOGICO" in texto or "FISIOLÓGICO" in texto:
        return 1.0, "L"

    return 1.0, "mL"




def coluna_numerica_segura(df, coluna):
    if coluna in df.columns:
        return pd.to_numeric(df[coluna], errors="coerce").fillna(0)
    return pd.Series([0] * len(df), index=df.index, dtype="float64")




def calcular_estoque_convertido(quantidade_compra, volume_por_unidade):
    try:
        return float(quantidade_compra or 0) * float(volume_por_unidade or 0)
    except Exception:
        return 0.0


def calcular_preco_por_controle(preco_total, estoque_convertido):
    try:
        preco_total = float(preco_total or 0)
        estoque_convertido = float(estoque_convertido or 0)
        if estoque_convertido <= 0:
            return 0.0
        return preco_total / estoque_convertido
    except Exception:
        return 0.0


def sugerir_unidade_controle(nome_medicamento="", unidade_atual=""):
    nome = str(nome_medicamento or "").lower()
    unidade_atual = str(unidade_atual or "").upper()
    if "soro" in nome or "ringer" in nome or "fisiologico" in nome or "fisiológico" in nome or unidade_atual in ["L", "LT", "LITRO", "LITROS"]:
        return "L"
    return "mL"



def recalcular_farmacia_por_descricao(somente_volume_igual_1=True):
    """
    Reprocessa medicamentos já importados para identificar automaticamente volume pela descrição.
    Útil para corrigir itens antigos que entraram como 1 mL.
    """
    df = pd.read_sql_query("SELECT * FROM farmacia", conn)
    if df.empty:
        return 0

    alterados = 0

    for _, row in df.iterrows():
        med_id = row["id"]
        medicamento = str(row.get("medicamento", "") or "")
        quantidade_compra = float(row.get("quantidade_compra") or row.get("quantidade") or 0)
        preco_total = float(row.get("preco") or 0)

        volume_atual = float(row.get("volume_por_unidade") or 0)
        volume_extraido, unidade_extraida = extrair_volume_descricao(medicamento)

        if somente_volume_igual_1 and volume_atual not in [0, 1]:
            continue

        if volume_extraido <= 1 and volume_atual not in [0, 1]:
            continue

        unidade_controle = unidade_extraida or sugerir_unidade_controle(medicamento, row.get("unidade", ""))

        estoque_convertido = calcular_estoque_convertido(quantidade_compra, volume_extraido)
        preco_por_controle = calcular_preco_por_controle(preco_total, estoque_convertido)

        c.execute("""
            UPDATE farmacia
            SET volume_por_unidade = ?,
                unidade_controle = ?,
                estoque_convertido = ?,
                quantidade_compra = ?,
                preco_por_controle = ?
            WHERE id = ?
        """, (
            str(volume_extraido),
            unidade_controle,
            str(estoque_convertido),
            str(quantidade_compra),
            str(preco_por_controle),
            str(med_id)
        ))

        alterados += 1

    conn.commit()
    return alterados



def atualizar_farmacia_antiga_para_controle():
    try:
        df = pd.read_sql_query("SELECT * FROM farmacia", conn)
        if df.empty:
            return

        for _, row in df.iterrows():
            med_id = row["id"]
            medicamento = row.get("medicamento", "")
            unidade_compra = row.get("unidade_compra", "") or row.get("unidade", "") or "FR"
            unidade_controle = row.get("unidade_controle", "") or sugerir_unidade_controle(medicamento, unidade_compra)
            quantidade_compra = row.get("quantidade_compra", "") or row.get("quantidade", 0) or 0
            volume_por_unidade = row.get("volume_por_unidade", "") or 1
            estoque_convertido = row.get("estoque_convertido", "")

            if estoque_convertido in [None, ""]:
                estoque_convertido = calcular_estoque_convertido(quantidade_compra, volume_por_unidade)

            estoque_min_controle = row.get("estoque_min_controle", "") or row.get("estoque_min", 0) or 0

            preco_total = float(row.get("preco", 0) or 0) * float(quantidade_compra or 0)
            preco_por_controle = row.get("preco_por_controle", "")
            if preco_por_controle in [None, ""]:
                preco_por_controle = calcular_preco_por_controle(preco_total, estoque_convertido)

            c.execute("""
                UPDATE farmacia
                SET quantidade_compra = ?,
                    unidade_compra = ?,
                    volume_por_unidade = ?,
                    unidade_controle = ?,
                    estoque_convertido = ?,
                    estoque_min_controle = ?,
                    preco_por_controle = ?
                WHERE id = ?
            """, (
                str(quantidade_compra),
                unidade_compra,
                str(volume_por_unidade),
                unidade_controle,
                str(estoque_convertido),
                str(estoque_min_controle),
                str(preco_por_controle),
                str(med_id)
            ))
        conn.commit()
    except Exception:
        pass




# =========================================================
# FICHA MÉDICA / PRESCRIÇÃO
# =========================================================

c.execute("""
CREATE TABLE IF NOT EXISTS fichas_medicas (
    id INTEGER PRIMARY KEY AUTOINCREMENT
)
""")

for col in [
    "animal", "tipo_animal", "data_atendimento", "motivo",
    "diagnostico", "tratamento_indicado", "veterinario",
    "retorno", "status", "custo_total", "obs"
]:
    add_col("fichas_medicas", col)

c.execute("""
CREATE TABLE IF NOT EXISTS ficha_medicacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT
)
""")

for col in [
    "ficha_id", "animal", "tipo_animal", "medicamento", "quantidade",
    "unidade", "dosagem", "data_hora", "funcionario", "telefone",
    "mensagem", "status", "alerta_gerado", "data_alerta",
    "preco_unitario", "custo_total", "obs"
]:
    add_col("ficha_medicacoes", col)

conn.commit()



# =========================================================
# SIDEBAR / MENU
# =========================================================

with st.sidebar:
    if os.path.exists(LOGO):
        st.image(LOGO, use_container_width=True)
    else:
        st.markdown("### Rancho Recanto Verde")

    st.markdown("#### Menu")

menu_map_total = {
    "🏠 Dashboard": "Dashboard",
    "🐎 Cadastrar Animal": "Cadastrar Animal",
    "📋 Animais por Tipo": "Animais por Tipo",
    "⚖️ Pesagem / Evolução": "Pesagem / Evolução",
    "💉 Controle Sanitário": "Controle Sanitário",
    "💊 Farmácia": "Farmácia",
    "📥 Importar NF-e / XML": "Importar NF-e / XML",
    "🔎 Consulta ABQM": "Consulta ABQM",
    "🩺 Veterinário / Tratamentos": "Veterinário / Tratamentos",
    "🧬 Reprodução / Embriões": "Reprodução / Embriões",
    "💰 Vendas de Animais": "Vendas de Animais",
    "👥 Funcionários": "Funcionários",
    "📲 Alertas WhatsApp": "Alertas WhatsApp",
    "📊 Relatórios / Gráficos": "Relatórios / Gráficos",
    "📄 Gerar PDF": "Gerar PDF",
    "⚙️ Admin / Usuários": "Admin / Usuários",
}

menu_map = {
    label: pagina
    for label, pagina in menu_map_total.items()
    if usuario_tem_permissao(pagina)
}

if not menu_map:
    st.error("Seu usuário não possui permissões liberadas.")
    st.stop()

# Estado da navegação
if "pagina_atual" not in st.session_state or st.session_state.pagina_atual not in menu_map.values():
    st.session_state.pagina_atual = list(menu_map.values())[0]

# Menu lateral
op_display = st.sidebar.radio(
    "Menu",
    list(menu_map.keys()),
    index=list(menu_map.values()).index(st.session_state.pagina_atual)
        if st.session_state.pagina_atual in list(menu_map.values()) else 0,
    label_visibility="collapsed"
)

# Se o usuário clicar no menu lateral, atualiza a página
st.session_state.pagina_atual = menu_map[op_display]

# Menu superior clicável com permissões
atalhos = [
    ("🏠 Dashboard", "Dashboard"),
    ("📊 Relatórios / Gráficos", "Relatórios / Gráficos"),
    ("📋 Animais por Tipo", "Animais por Tipo"),
    ("💉 Controle Sanitário", "Controle Sanitário"),
]

atalhos = [(label, pagina) for label, pagina in atalhos if usuario_tem_permissao(pagina)]

if atalhos:
    cols = st.columns(len(atalhos))
    for col, (label, pagina) in zip(cols, atalhos):
        with col:
            if st.button(label, use_container_width=True):
                st.session_state.pagina_atual = pagina
                st.rerun()

op = st.session_state.pagina_atual

st.markdown("---")


# =========================================================
# DASHBOARD - HOME ESTILO APP PROFISSIONAL
# =========================================================

if op == "Dashboard":
    animais = pd.read_sql_query("SELECT * FROM animais WHERE nome IS NOT NULL AND nome != ''", conn)
    farmacia = pd.read_sql_query("SELECT * FROM farmacia WHERE medicamento IS NOT NULL AND medicamento != ''", conn)
    sanitario = pd.read_sql_query("SELECT * FROM sanitario WHERE animal IS NOT NULL", conn)
    tratamentos = pd.read_sql_query("SELECT * FROM tratamentos WHERE animal IS NOT NULL", conn)
    vendas = pd.read_sql_query("SELECT * FROM vendas WHERE animal IS NOT NULL", conn)
    recebimentos = pd.read_sql_query("SELECT * FROM recebimentos WHERE animal IS NOT NULL", conn)
    receptoras = pd.read_sql_query("SELECT * FROM receptoras WHERE receptora IS NOT NULL", conn)

    total_animais = len(animais)
    total_equinos = len(animais[animais["tipo"] == "Equino"]) if not animais.empty else 0

    alertas_sanitarios = 0
    if not sanitario.empty:
        sanitario["status_alerta"] = sanitario["proxima_dose"].apply(lambda x: status_data(x, 30))
        alertas_sanitarios = len(sanitario[sanitario["status_alerta"].isin(["VENCIDO", "PRÓXIMO"])])

    estoque_baixo = 0
    if not farmacia.empty:
        farmacia["quantidade_num"] = pd.to_numeric(farmacia["quantidade"], errors="coerce").fillna(0)
        farmacia["estoque_min_num"] = pd.to_numeric(farmacia["estoque_min"], errors="coerce").fillna(0)
        estoque_baixo = len(farmacia[(farmacia["quantidade_num"] <= farmacia["estoque_min_num"]) | (farmacia["quantidade_num"] <= 0)])

    total_aberto = 0.0
    total_recebido = 0.0
    recebimentos_atrasados = 0
    if not recebimentos.empty:
        recebimentos["valor_num"] = pd.to_numeric(recebimentos["valor"], errors="coerce").fillna(0)
        total_recebido = recebimentos[recebimentos["status"] == "Pago"]["valor_num"].sum()
        total_aberto = recebimentos[recebimentos["status"] != "Pago"]["valor_num"].sum()
        recebimentos["venc_dt"] = pd.to_datetime(recebimentos["vencimento"], format="%d/%m/%Y", errors="coerce")
        recebimentos_atrasados = len(recebimentos[(recebimentos["status"] != "Pago") & (recebimentos["venc_dt"].dt.date < date.today())])

    total_vendido = 0.0
    if not vendas.empty:
        vendas["valor_num"] = pd.to_numeric(vendas["valor_final"], errors="coerce").fillna(0)
        total_vendido = vendas["valor_num"].sum()

    custo_total = 0.0
    if not tratamentos.empty:
        tratamentos["custo_num"] = pd.to_numeric(tratamentos["custo_total"], errors="coerce").fillna(0)
        custo_total += tratamentos["custo_num"].sum()
    if not sanitario.empty:
        sanitario["custo_num"] = pd.to_numeric(sanitario["custo_total"], errors="coerce").fillna(0)
        custo_total += sanitario["custo_num"].sum()

    receptoras_prenhes = 0
    partos_proximos = 0
    if not receptoras.empty:
        receptoras_prenhes = len(receptoras[receptoras["status"] == "Prenhe"])
        receptoras["status_parto"] = receptoras["previsao_parto"].apply(lambda x: status_data(x, 30))
        partos_proximos = len(receptoras[receptoras["status_parto"].isin(["VENCIDO", "PRÓXIMO"])])

    st.markdown('<div class="quick-title">🐎 Rancho Recanto Verde</div>', unsafe_allow_html=True)
    st.markdown('<div class="quick-subtitle">Organização completa do haras na palma da mão</div>', unsafe_allow_html=True)

    st.markdown("### Acesso rápido")

    linha1 = st.columns(4)
    atalhos = [
        ("🐎", "Animais", "Cadastros e histórico", "Animais por Tipo"),
        ("💉", "Saúde", "Vacinas e vermífugos", "Controle Sanitário"),
        ("💊", "Farmácia", "Estoque e custos", "Farmácia"),
        ("💰", "Financeiro", "Vendas e recebimentos", "Vendas de Animais"),
    ]

    for col, (icone, titulo, subtitulo, pagina) in zip(linha1, atalhos):
        with col:
            st.markdown(f"""
            <div class="app-grid-card">
                <div class="app-grid-icon">{icone}</div>
                <div class="app-grid-title">{titulo}</div>
                <div class="app-grid-subtitle">{subtitulo}</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"Abrir {titulo}", key=f"atalho_{pagina}", use_container_width=True):
                st.session_state.pagina_atual = pagina
                st.rerun()

    linha2 = st.columns(4)
    atalhos2 = [
        ("🩺", "Veterinário", "Tratamentos e retornos", "Veterinário / Tratamentos"),
        ("🧬", "Reprodução", "Doadoras e receptoras", "Reprodução / Embriões"),
        ("👥", "Funcionários", "Equipe e documentos", "Funcionários"),
        ("📲", "WhatsApp", "Alertas para equipe", "Alertas WhatsApp"),
    ]

    for col, (icone, titulo, subtitulo, pagina) in zip(linha2, atalhos2):
        with col:
            st.markdown(f"""
            <div class="app-grid-card">
                <div class="app-grid-icon">{icone}</div>
                <div class="app-grid-title">{titulo}</div>
                <div class="app-grid-subtitle">{subtitulo}</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"Abrir {titulo}", key=f"atalho_{pagina}", use_container_width=True):
                st.session_state.pagina_atual = pagina
                st.rerun()

    st.markdown("---")
    st.markdown("### Resumo do haras")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Animais", total_animais, f"{total_equinos} equinos")
    with c2:
        st.metric("Saúde", alertas_sanitarios, "alertas sanitários")
    with c3:
        st.metric("Farmácia", estoque_baixo, "itens baixos")
    with c4:
        st.metric("Reprodução", receptoras_prenhes, f"{partos_proximos} partos próximos")

    c5, c6, c7, c8 = st.columns(4)
    with c5:
        st.metric("Total vendido", moeda(total_vendido))
    with c6:
        st.metric("Recebido", moeda(total_recebido))
    with c7:
        st.metric("A receber", moeda(total_aberto), f"{recebimentos_atrasados} atrasadas")
    with c8:
        st.metric("Custos", moeda(custo_total))

    st.markdown("---")
    st.markdown("### Alertas importantes")

    a1, a2, a3 = st.columns(3)

    with a1:
        st.markdown("#### 💉 Saúde em dia")
        if not sanitario.empty:
            alerta_san = sanitario[sanitario["status_alerta"].isin(["VENCIDO", "PRÓXIMO"])]
            if not alerta_san.empty:
                st.dataframe(alerta_san[["animal", "procedimento", "produto", "proxima_dose", "status_alerta"]].head(5), use_container_width=True, hide_index=True)
            else:
                st.success("Nenhuma vacina ou vermífugo vencendo.")
        else:
            st.info("Nenhum controle sanitário registrado.")

    with a2:
        st.markdown("#### 💊 Estoque")
        if not farmacia.empty:
            alerta_farmacia = farmacia[(farmacia["quantidade_num"] <= farmacia["estoque_min_num"]) | (farmacia["quantidade_num"] <= 0)]
            if not alerta_farmacia.empty:
                st.dataframe(alerta_farmacia[["medicamento", "quantidade", "estoque_min", "unidade"]].head(5), use_container_width=True, hide_index=True)
            else:
                st.success("Estoque adequado.")
        else:
            st.info("Nenhum medicamento cadastrado.")

    with a3:
        st.markdown("#### 💰 Financeiro")
        if not recebimentos.empty:
            abertos = recebimentos[recebimentos["status"] != "Pago"]
            if not abertos.empty:
                st.dataframe(abertos[["animal", "comprador", "vencimento", "valor", "status"]].head(5), use_container_width=True, hide_index=True)
            else:
                st.success("Nenhum recebimento em aberto.")
        else:
            st.info("Nenhum recebimento cadastrado.")

    st.markdown("---")
    st.caption("Tela inicial simplificada para uso no celular. Gráficos completos ficam em Relatórios / Gráficos.")


# =========================================================
# CADASTRAR ANIMAL
# =========================================================

elif op == "Cadastrar Animal":
    titulo_pagina("🐎 Cadastro de Animal", "Cadastre os dados básicos do animal")

    col1, col2 = st.columns(2)

    with col1:
        nome = st.text_input("Nome do animal")
        tipo = st.selectbox("Tipo", tipos)
        especie = st.text_input("Espécie")
        raca = st.text_input("Raça")
        sexo = st.selectbox("Sexo", ["Macho", "Fêmea"])
        nascimento = st.date_input("Nascimento", format="DD/MM/YYYY")
        cor = st.text_input("Pelagem / Cor")

    with col2:
        responsavel = st.text_input("Responsável")
        cpf = st.text_input("CPF")
        telefone = st.text_input("Telefone")
        local = st.text_input("Local / Baia / Piquete / Canil / Curral")
        microchip = st.text_input("Microchip / Identificação")
        status_animal = st.selectbox("Status", ["Ativo", "Vendido", "Óbito", "Transferido", "Outro"])

    st.markdown("### Dados ABQM (opcional)")
    col_abqm1, col_abqm2 = st.columns(2)

    with col_abqm1:
        registro_abqm = st.text_input("Registro ABQM")
        nome_oficial_abqm = st.text_input("Nome oficial ABQM")
        pai_abqm = st.text_input("Pai")
        mae_abqm = st.text_input("Mãe")

    with col_abqm2:
        criador_abqm = st.text_input("Criador")
        proprietario_abqm = st.text_input("Proprietário")
        link_abqm = st.text_input("Link da consulta ABQM")
        obs_abqm = st.text_area("Observações ABQM")

    obs = st.text_area("Observações gerais")

    if st.button("Salvar Animal"):
        c.execute("""
            INSERT INTO animais
            (nome, tipo, especie, raca, sexo, nascimento, cor,
             responsavel, cpf, telefone, local, microchip, status,
             registro_abqm, nome_oficial_abqm, pai_abqm, mae_abqm,
             criador_abqm, proprietario_abqm, link_abqm, obs_abqm,
             obs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            nome, tipo, especie, raca, sexo, br_data(nascimento), cor,
            responsavel, cpf, telefone, local, microchip, status_animal,
            registro_abqm, nome_oficial_abqm, pai_abqm, mae_abqm,
            criador_abqm, proprietario_abqm, link_abqm, obs_abqm,
            obs
        ))
        conn.commit()
        st.success("Animal cadastrado com sucesso!")


# =========================================================
# ANIMAIS POR TIPO
# =========================================================

elif op == "Animais por Tipo":
    titulo_pagina("📋 Animais por Tipo", "Consulte, filtre e altere os animais cadastrados")

    aba = st.radio(
        "Opção",
        ["Consultar Animais", "Alterar Animal"],
        horizontal=True
    )

    df = listar_animais()

    if df.empty:
        st.warning("Nenhum animal cadastrado ainda.")
    else:
        if aba == "Consultar Animais":
            col1, col2 = st.columns(2)

            with col1:
                filtro = st.selectbox("Filtrar por tipo", ["Todos"] + tipos)

            with col2:
                filtro_status = st.selectbox("Filtrar por status", ["Todos", "Ativo", "Vendido", "Óbito", "Transferido", "Outro"])

            df_view = df.copy()

            if filtro != "Todos":
                df_view = df_view[df_view["tipo"] == filtro]

            if filtro_status != "Todos":
                df_view = df_view[df_view["status"] == filtro_status]

            st.dataframe(df_view, use_container_width=True)

            st.download_button(
                "📥 Baixar Excel",
                data=gerar_excel(df_view),
                file_name="animais_rancho_recanto_verde.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        elif aba == "Alterar Animal":
            st.markdown("### Alterar cadastro do animal")

            df["descricao"] = df["id"].astype(str) + " - " + df["nome"].fillna("") + " - " + df["tipo"].fillna("")
            escolha = st.selectbox("Escolha o animal", df["descricao"].tolist())
            animal_id = escolha.split(" - ")[0]

            animal = pd.read_sql_query(
                "SELECT * FROM animais WHERE id = ?",
                conn,
                params=(animal_id,)
            ).iloc[0]

            col1, col2 = st.columns(2)

            with col1:
                nome = st.text_input("Nome do animal", value=str(animal.get("nome", "") or ""))
                tipo = st.selectbox(
                    "Tipo",
                    tipos,
                    index=tipos.index(animal["tipo"]) if animal.get("tipo") in tipos else 0
                )
                especie = st.text_input("Espécie", value=str(animal.get("especie", "") or ""))
                raca = st.text_input("Raça", value=str(animal.get("raca", "") or ""))
                sexo = st.selectbox(
                    "Sexo",
                    ["Macho", "Fêmea"],
                    index=0 if animal.get("sexo") != "Fêmea" else 1
                )
                nascimento_txt = st.text_input("Nascimento", value=str(animal.get("nascimento", "") or ""))
                cor = st.text_input("Pelagem / Cor", value=str(animal.get("cor", "") or ""))

            with col2:
                responsavel = st.text_input("Responsável", value=str(animal.get("responsavel", "") or ""))
                cpf = st.text_input("CPF", value=str(animal.get("cpf", "") or ""))
                telefone = st.text_input("Telefone", value=str(animal.get("telefone", "") or ""))
                local = st.text_input("Local / Baia / Piquete", value=str(animal.get("local", "") or ""))
                microchip = st.text_input("Microchip / Identificação", value=str(animal.get("microchip", "") or ""))
                status_opcoes = ["Ativo", "Vendido", "Óbito", "Transferido", "Outro"]
                status_animal = st.selectbox(
                    "Status",
                    status_opcoes,
                    index=status_opcoes.index(animal["status"]) if animal.get("status") in status_opcoes else 0
                )

            st.markdown("### Dados ABQM")
            col_abqm1, col_abqm2 = st.columns(2)

            with col_abqm1:
                registro_abqm = st.text_input("Registro ABQM", value=str(animal.get("registro_abqm", "") or ""))
                nome_oficial_abqm = st.text_input("Nome oficial ABQM", value=str(animal.get("nome_oficial_abqm", "") or ""))
                pai_abqm = st.text_input("Pai", value=str(animal.get("pai_abqm", "") or ""))
                mae_abqm = st.text_input("Mãe", value=str(animal.get("mae_abqm", "") or ""))

            with col_abqm2:
                criador_abqm = st.text_input("Criador", value=str(animal.get("criador_abqm", "") or ""))
                proprietario_abqm = st.text_input("Proprietário", value=str(animal.get("proprietario_abqm", "") or ""))
                link_abqm = st.text_input("Link da consulta ABQM", value=str(animal.get("link_abqm", "") or ""))
                obs_abqm = st.text_area("Observações ABQM", value=str(animal.get("obs_abqm", "") or ""))

            obs = st.text_area("Observações gerais", value=str(animal.get("obs", "") or ""))

            col_btn1, col_btn2 = st.columns(2)

            with col_btn1:
                if st.button("💾 Salvar Alterações do Animal", use_container_width=True):
                    c.execute("""
                        UPDATE animais
                        SET nome = ?, tipo = ?, especie = ?, raca = ?, sexo = ?,
                            nascimento = ?, cor = ?, responsavel = ?, cpf = ?,
                            telefone = ?, local = ?, microchip = ?, status = ?,
                            registro_abqm = ?, nome_oficial_abqm = ?, pai_abqm = ?,
                            mae_abqm = ?, criador_abqm = ?, proprietario_abqm = ?,
                            link_abqm = ?, obs_abqm = ?, obs = ?
                        WHERE id = ?
                    """, (
                        nome, tipo, especie, raca, sexo,
                        nascimento_txt, cor, responsavel, cpf,
                        telefone, local, microchip, status_animal,
                        registro_abqm, nome_oficial_abqm, pai_abqm,
                        mae_abqm, criador_abqm, proprietario_abqm,
                        link_abqm, obs_abqm, obs,
                        animal_id
                    ))
                    conn.commit()
                    st.success("Animal alterado com sucesso!")
                    st.rerun()

            with col_btn2:
                confirmar = st.checkbox("Confirmar exclusão deste animal")
                if st.button("🗑️ Excluir Animal", use_container_width=True):
                    if confirmar:
                        c.execute("DELETE FROM animais WHERE id = ?", (animal_id,))
                        conn.commit()
                        st.success("Animal excluído com sucesso!")
                        st.rerun()
                    else:
                        st.error("Marque a confirmação para excluir.")


# =========================================================
# PESAGEM / EVOLUÇÃO
# =========================================================

elif op == "Pesagem / Evolução":
    titulo_pagina("⚖️ Pesagem / Evolução", "Acompanhe o peso dos animais ao longo do tempo")

    aba = st.radio("Opção", ["Registrar Pesagem", "Histórico de Pesagens"], horizontal=True)
    animais = listar_animais()

    if aba == "Registrar Pesagem":
        if animais.empty:
            st.warning("Cadastre um animal primeiro.")
        else:
            animais["descricao"] = animais["nome"] + " - " + animais["tipo"]
            escolha = st.selectbox("Animal", animais["descricao"].tolist())

            animal_nome = escolha.split(" - ")[0]
            animal_tipo = escolha.split(" - ")[1]

            data_pesagem = st.date_input("Data da pesagem", format="DD/MM/YYYY")
            peso = st.number_input("Peso", min_value=0.0, step=1.0)
            obs = st.text_area("Observações")

            if st.button("Salvar Pesagem"):
                c.execute("""
                    INSERT INTO pesagens (animal, tipo, data_pesagem, peso, obs)
                    VALUES (?, ?, ?, ?, ?)
                """, (animal_nome, animal_tipo, br_data(data_pesagem), str(peso), obs))
                conn.commit()
                st.success("Pesagem registrada com sucesso!")

    elif aba == "Histórico de Pesagens":
        df = pd.read_sql_query("SELECT * FROM pesagens WHERE animal IS NOT NULL", conn)

        if not df.empty:
            filtro = st.selectbox("Filtrar por tipo", ["Todos"] + tipos)
            if filtro != "Todos":
                df = df[df["tipo"] == filtro]

            animal_filtro = st.selectbox("Filtrar por animal", ["Todos"] + sorted(df["animal"].dropna().unique().tolist()))
            if animal_filtro != "Todos":
                df = df[df["animal"] == animal_filtro]

            st.dataframe(df, use_container_width=True)

            df_grafico = df.copy()
            df_grafico["peso"] = pd.to_numeric(df_grafico["peso"], errors="coerce")
            df_grafico["data_pesagem_dt"] = pd.to_datetime(df_grafico["data_pesagem"], format="%d/%m/%Y", errors="coerce")
            df_grafico = df_grafico.dropna(subset=["peso", "data_pesagem_dt"]).sort_values("data_pesagem_dt")

            if animal_filtro != "Todos" and not df_grafico.empty:
                st.line_chart(df_grafico.set_index("data_pesagem_dt")["peso"])

            st.download_button(
                "📥 Baixar Histórico de Pesagens",
                data=gerar_excel(df),
                file_name="historico_pesagens.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("Nenhuma pesagem registrada ainda.")


# =========================================================
# CONTROLE SANITÁRIO
# =========================================================

elif op == "Controle Sanitário":
    titulo_pagina("💉 Controle Sanitário", "Vacinas, vermifugação e alertas de próxima dose")

    aba = st.radio(
        "Opção",
        ["Registrar Vacina", "Registrar Vermifugação", "Alertas Sanitários", "Histórico Sanitário"],
        horizontal=True
    )

    animais = listar_animais()
    farmacia = listar_farmacia()

    if aba in ["Registrar Vacina", "Registrar Vermifugação"]:
        procedimento = "Vacina" if aba == "Registrar Vacina" else "Vermífugo"
        categoria_busca = "Vacina" if procedimento == "Vacina" else "Vermífugo"

        produtos = farmacia[farmacia["categoria"] == categoria_busca] if not farmacia.empty else pd.DataFrame()

        if animais.empty:
            st.warning("Cadastre um animal primeiro.")
        elif produtos.empty:
            st.warning(f"Cadastre primeiro um produto na Farmácia com categoria '{categoria_busca}'.")
        else:
            animais["descricao"] = animais["nome"] + " - " + animais["tipo"]
            escolha = st.selectbox("Animal", animais["descricao"].tolist())
            animal_nome = escolha.split(" - ")[0]
            animal_tipo = escolha.split(" - ")[1]

            produto = st.selectbox(f"{categoria_busca} cadastrada na farmácia", produtos["medicamento"].tolist())
            produto_df = produtos[produtos["medicamento"] == produto].iloc[0]

            estoque_atual = float(produto_df["quantidade"] or 0)
            preco_unitario = float(produto_df["preco"] or 0)
            unidade_padrao = produto_df["unidade"] or ""

            st.info(f"Estoque atual: {estoque_atual} {unidade_padrao} | Preço unitário: {moeda(preco_unitario)}")

            col1, col2 = st.columns(2)
            with col1:
                data_aplicacao = st.date_input("Data da aplicação", format="DD/MM/YYYY")
                proxima_dose = st.date_input("Próxima dose / próxima vermifugação", format="DD/MM/YYYY")
                quantidade_usada = st.number_input("Quantidade usada", min_value=0.0, step=1.0)
            with col2:
                unidade = st.text_input("Unidade usada", value=unidade_padrao)
                responsavel = st.text_input("Veterinário / Responsável")
                obs = st.text_area("Observações")

            custo_total = quantidade_usada * preco_unitario
            st.metric("Custo da aplicação", moeda(custo_total))

            if st.button("Salvar e Baixar Estoque"):
                if quantidade_usada <= 0:
                    st.error("Informe a quantidade usada.")
                    st.stop()

                ok, nova_qtd, preco_unitario, erro = baixar_estoque(produto, quantidade_usada)
                if not ok:
                    st.error(erro)
                    st.stop()

                c.execute("""
                    INSERT INTO sanitario
                    (animal, tipo, procedimento, produto, data_aplicacao, proxima_dose,
                     quantidade_usada, unidade, preco_unitario, custo_total, responsavel, obs)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    animal_nome, animal_tipo, procedimento, produto, br_data(data_aplicacao),
                    br_data(proxima_dose), str(quantidade_usada), unidade,
                    str(preco_unitario), str(custo_total), responsavel, obs
                ))
                conn.commit()
                st.success(f"{procedimento} registrada. Estoque baixado. Custo: {moeda(custo_total)}")

    elif aba == "Alertas Sanitários":
        df = pd.read_sql_query("SELECT * FROM sanitario WHERE animal IS NOT NULL", conn)

        if not df.empty:
            df["status"] = df["proxima_dose"].apply(lambda x: status_data(x, 30))
            alertas = df[df["status"].isin(["VENCIDO", "PRÓXIMO"])]

            if not alertas.empty:
                st.warning("⚠️ Existem vacinas ou vermifugações vencidas/próximas.")
                st.dataframe(alertas, use_container_width=True)
            else:
                st.success("Nenhum alerta sanitário no momento.")

            st.dataframe(df, use_container_width=True)
        else:
            st.warning("Nenhuma aplicação sanitária registrada.")

    elif aba == "Histórico Sanitário":
        df = pd.read_sql_query("SELECT * FROM sanitario WHERE animal IS NOT NULL", conn)

        if not df.empty:
            col1, col2 = st.columns(2)
            with col1:
                filtro_proc = st.selectbox("Filtrar procedimento", ["Todos", "Vacina", "Vermífugo"])
            with col2:
                filtro_tipo = st.selectbox("Filtrar tipo animal", ["Todos"] + tipos)

            if filtro_proc != "Todos":
                df = df[df["procedimento"] == filtro_proc]
            if filtro_tipo != "Todos":
                df = df[df["tipo"] == filtro_tipo]

            df["status"] = df["proxima_dose"].apply(lambda x: status_data(x, 30))
            st.dataframe(df, use_container_width=True)

            st.download_button(
                "📥 Baixar Histórico Sanitário",
                data=gerar_excel(df),
                file_name="historico_sanitario.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("Nenhum histórico sanitário registrado.")


# =========================================================
# CONSULTA ABQM
# =========================================================

elif op == "Consulta ABQM":
    titulo_pagina("🔎 Consulta ABQM", "Consulta assistida e cadastro de dados oficiais ABQM")

    st.info("A consulta oficial da ABQM exige login no site. Esta aba permite abrir o site oficial e salvar os dados consultados dentro do sistema.")

    aba = st.radio(
        "Opção",
        ["Consultar / Cadastrar Dados", "Histórico ABQM"],
        horizontal=True
    )

    animais = listar_animais()

    if aba == "Consultar / Cadastrar Dados":
        termo = st.text_input("Digite nome ou registro ABQM para consulta")
        st.link_button("🔎 Abrir Consulta Oficial ABQM", link_consulta_abqm(termo), use_container_width=True)

        st.markdown("---")
        st.markdown("### Salvar dados ABQM no sistema")

        if animais.empty:
            st.warning("Cadastre um animal primeiro para vincular os dados ABQM.")
        else:
            animais["descricao"] = animais["nome"] + " - " + animais["tipo"]
            escolha = st.selectbox("Vincular ao animal", animais["descricao"].tolist())
            animal_nome = escolha.split(" - ")[0]

            animal_atual = pd.read_sql_query(
                "SELECT * FROM animais WHERE nome = ?",
                conn,
                params=(animal_nome,)
            ).iloc[0]

            col1, col2 = st.columns(2)

            with col1:
                registro_abqm = st.text_input("Registro ABQM", value=str(animal_atual.get("registro_abqm", "") or termo or ""))
                nome_oficial = st.text_input("Nome oficial", value=str(animal_atual.get("nome_oficial_abqm", "") or animal_nome))
                pai = st.text_input("Pai", value=str(animal_atual.get("pai_abqm", "") or ""))
                mae = st.text_input("Mãe", value=str(animal_atual.get("mae_abqm", "") or ""))
                pelagem = st.text_input("Pelagem", value=str(animal_atual.get("cor", "") or ""))

            with col2:
                nascimento = st.text_input("Nascimento", value=str(animal_atual.get("nascimento", "") or ""))
                criador = st.text_input("Criador", value=str(animal_atual.get("criador_abqm", "") or ""))
                proprietario = st.text_input("Proprietário", value=str(animal_atual.get("proprietario_abqm", "") or ""))
                link_consulta = st.text_input("Link/observação da consulta", value=str(animal_atual.get("link_abqm", "") or link_consulta_abqm(termo)))
                observacoes = st.text_area("Observações", value=str(animal_atual.get("obs_abqm", "") or ""))

            if st.button("Salvar dados ABQM no animal"):
                c.execute("""
                    UPDATE animais
                    SET registro_abqm = ?, nome_oficial_abqm = ?, pai_abqm = ?,
                        mae_abqm = ?, criador_abqm = ?, proprietario_abqm = ?,
                        link_abqm = ?, obs_abqm = ?
                    WHERE nome = ?
                """, (
                    registro_abqm, nome_oficial, pai, mae, criador,
                    proprietario, link_consulta, observacoes, animal_nome
                ))

                c.execute("""
                    INSERT INTO abqm_consultas
                    (animal, registro_abqm, nome_oficial, pai, mae,
                     pelagem, nascimento, criador, proprietario,
                     link_consulta, observacoes, data_cadastro)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    animal_nome, registro_abqm, nome_oficial, pai, mae,
                    pelagem, nascimento, criador, proprietario,
                    link_consulta, observacoes,
                    datetime.now().strftime("%d/%m/%Y %H:%M")
                ))

                conn.commit()
                st.success("Dados ABQM salvos e vinculados ao animal!")

    elif aba == "Histórico ABQM":
        df = pd.read_sql_query("SELECT * FROM abqm_consultas WHERE animal IS NOT NULL", conn)

        if not df.empty:
            st.dataframe(df, use_container_width=True)

            st.download_button(
                "📥 Baixar Histórico ABQM",
                data=gerar_excel(df),
                file_name="historico_abqm.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("Nenhuma consulta ABQM salva ainda.")


# =========================================================
# IMPORTAR NF-e / XML
# =========================================================

elif op == "Importar NF-e / XML":
    titulo_pagina("📥 Importar NF-e / XML", "Importe produtos da nota fiscal diretamente para a Farmácia")

    st.info("O código de barras da NF-e normalmente identifica a chave de acesso. Para trazer os produtos automaticamente, envie o XML da NF-e.")

    arquivo_xml = st.file_uploader("Enviar XML da NF-e", type=["xml"])

    if arquivo_xml is not None:
        try:
            dados_nfe = ler_xml_nfe(arquivo_xml.read())
            produtos = dados_nfe["produtos"]

            st.markdown("### Dados da NF-e")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Número NF-e", dados_nfe["numero_nfe"] or "-")
            with col2:
                st.metric("Fornecedor", dados_nfe["fornecedor"][:22] if dados_nfe["fornecedor"] else "-")
            with col3:
                st.metric("Produtos", len(produtos))

            if not produtos:
                st.warning("Nenhum produto encontrado no XML.")
            else:
                df_produtos = pd.DataFrame(produtos)
                df_produtos["categoria"] = "Outro"
                df_produtos["estoque_min"] = 0.0
                df_produtos["validade"] = ""
                df_produtos["importar"] = True

                df_produtos["volume_por_unidade"] = df_produtos["produto"].apply(lambda x: extrair_volume_descricao(x)[0])
                df_produtos["unidade_controle"] = df_produtos["produto"].apply(lambda x: extrair_volume_descricao(x)[1])
                df_produtos["estoque_convertido"] = df_produtos.apply(
                    lambda r: calcular_estoque_convertido(limpar_numero(r["quantidade"]), limpar_numero(r["volume_por_unidade"])),
                    axis=1
                )
                df_produtos["preco_por_controle"] = df_produtos.apply(
                    lambda r: calcular_preco_por_controle(limpar_numero(r["valor_total"]), limpar_numero(r["estoque_convertido"])),
                    axis=1
                )

                st.markdown("### Produtos encontrados")
                st.caption("Revise os dados antes de importar. Validade normalmente não vem no XML e pode ser ajustada depois na Farmácia. O valor importado para estoque será o VALOR TOTAL do item da NF-e. O sistema também tentará identificar automaticamente o volume na descrição, como 50ML, 100ML ou 1L.")

                df_editado = st.data_editor(
                    df_produtos[[
                        "importar", "produto", "ncm", "quantidade", "unidade",
                        "valor_unitario", "valor_total", "volume_por_unidade",
                        "unidade_controle", "estoque_convertido", "preco_por_controle",
                        "categoria", "estoque_min", "validade"
                    ]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "categoria": st.column_config.SelectboxColumn(
                            "categoria",
                            options=["Antibiótico", "Anti-inflamatório", "Vermífugo", "Vacina", "Suplemento", "Curativo", "Hormônio", "Reprodução", "Outro"]
                        )
                    }
                )

                if st.button("Importar produtos selecionados para Farmácia"):
                    importados = 0
                    atualizados = 0

                    for _, row in df_editado.iterrows():
                        if not bool(row.get("importar", False)):
                            continue

                        produto_nome = str(row["produto"]).strip()
                        if not produto_nome:
                            continue

                        quantidade = limpar_numero(row["quantidade"])
                        preco = limpar_numero(row["valor_unitario"])
                        unidade = str(row["unidade"])
                        categoria = str(row["categoria"])
                        estoque_min = limpar_numero(row["estoque_min"])
                        validade = str(row["validade"] or "")

                        existente = pd.read_sql_query(
                            "SELECT * FROM farmacia WHERE medicamento = ?",
                            conn,
                            params=(produto_nome,)
                        )

                        if existente.empty:
                            valor_total_item = limpar_numero(row["valor_total"])
                            volume_por_unidade = limpar_numero(row.get("volume_por_unidade", 0))
                            unidade_controle = str(row.get("unidade_controle", "") or "").strip()
                            if not volume_por_unidade:
                                volume_por_unidade, unidade_controle_extraida = extrair_volume_descricao(produto_nome)
                                unidade_controle = unidade_controle or unidade_controle_extraida

                            unidade_controle = unidade_controle or sugerir_unidade_controle(produto_nome, unidade)
                            estoque_convertido = calcular_estoque_convertido(quantidade, volume_por_unidade)
                            preco_por_controle = calcular_preco_por_controle(valor_total_item, estoque_convertido)

                            c.execute("""
                                INSERT INTO farmacia
                                (medicamento, categoria, quantidade, estoque_min, unidade,
                                 preco, validade, fornecedor, obs,
                                 quantidade_compra, unidade_compra, volume_por_unidade,
                                 unidade_controle, estoque_convertido, estoque_min_controle,
                                 preco_por_controle)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                produto_nome,
                                categoria,
                                str(quantidade),
                                str(estoque_min),
                                unidade,
                                str(valor_total_item),
                                validade,
                                dados_nfe["fornecedor"],
                                f"Importado da NF-e {dados_nfe['numero_nfe']} | Valor total do item",
                                str(quantidade),
                                unidade,
                                str(volume_por_unidade),
                                unidade_controle,
                                str(estoque_convertido),
                                str(estoque_min),
                                str(preco_por_controle)
                            ))
                            importados += 1
                        else:
                            qtd_atual = limpar_numero(existente.iloc[0]["quantidade"])
                            nova_qtd = qtd_atual + quantidade

                            valor_total_item = limpar_numero(row["valor_total"])
                            preco_atual_total = limpar_numero(existente.iloc[0].get("preco", 0))
                            novo_preco_total = preco_atual_total + valor_total_item

                            unidade_controle_existente = existente.iloc[0].get("unidade_controle", "")
                            volume_existente = limpar_numero(existente.iloc[0].get("volume_por_unidade", 0))

                            volume_editado = limpar_numero(row.get("volume_por_unidade", 0))
                            unidade_editada = str(row.get("unidade_controle", "") or "").strip()
                            volume_extraido, unidade_extraida = extrair_volume_descricao(produto_nome)

                            unidade_controle = unidade_editada or unidade_controle_existente or unidade_extraida or sugerir_unidade_controle(produto_nome, unidade)
                            volume_por_unidade = volume_editado or (volume_existente if volume_existente > 1 else volume_extraido)

                            estoque_convertido_atual = limpar_numero(existente.iloc[0].get("estoque_convertido", 0))
                            estoque_convertido_entrada = calcular_estoque_convertido(quantidade, volume_por_unidade)
                            novo_estoque_convertido = estoque_convertido_atual + estoque_convertido_entrada

                            preco_por_controle = calcular_preco_por_controle(novo_preco_total, novo_estoque_convertido)

                            c.execute("""
                                UPDATE farmacia
                                SET quantidade = ?,
                                    preco = ?,
                                    fornecedor = ?,
                                    quantidade_compra = ?,
                                    unidade_compra = ?,
                                    volume_por_unidade = ?,
                                    unidade_controle = ?,
                                    estoque_convertido = ?,
                                    preco_por_controle = ?
                                WHERE medicamento = ?
                            """, (
                                str(nova_qtd),
                                str(novo_preco_total),
                                dados_nfe["fornecedor"],
                                str(nova_qtd),
                                unidade,
                                str(volume_por_unidade),
                                unidade_controle,
                                str(novo_estoque_convertido),
                                str(preco_por_controle),
                                produto_nome
                            ))
                            atualizados += 1

                        c.execute("""
                            INSERT INTO compras_nfe
                            (chave_nfe, numero_nfe, data_emissao, fornecedor,
                             cnpj_fornecedor, produto, ncm, quantidade, unidade,
                             valor_unitario, valor_total, data_importacao)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            dados_nfe["chave_nfe"],
                            dados_nfe["numero_nfe"],
                            dados_nfe["data_emissao"],
                            dados_nfe["fornecedor"],
                            dados_nfe["cnpj_fornecedor"],
                            produto_nome,
                            str(row["ncm"]),
                            str(quantidade),
                            unidade,
                            str(preco),
                            str(limpar_numero(row["valor_total"])),
                            datetime.now().strftime("%d/%m/%Y %H:%M")
                        ))

                    conn.commit()
                    st.success(f"Importação concluída: {importados} novos itens e {atualizados} itens atualizados no estoque.")

        except Exception as e:
            st.error(f"Não foi possível ler o XML: {e}")

    st.markdown("---")
    st.markdown("### Histórico de compras importadas")

    hist = pd.read_sql_query("SELECT * FROM compras_nfe WHERE produto IS NOT NULL", conn)
    if not hist.empty:
        st.dataframe(hist, use_container_width=True)
        st.download_button(
            "📥 Baixar Histórico de Compras",
            data=gerar_excel(hist),
            file_name="historico_compras_nfe.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("Nenhuma compra importada ainda.")


# =========================================================
# FARMÁCIA
# =========================================================

elif op == "Farmácia":
    titulo_pagina("💊 Farmácia", "Controle de estoque, custo e conversão para mL/L")

    atualizar_farmacia_antiga_para_controle()

    aba = st.radio(
        "Opção",
        ["Cadastrar Medicamento", "Estoque", "Alterar Medicamento", "Alertas de Estoque"],
        horizontal=True
    )

    if aba == "Cadastrar Medicamento":
        col1, col2 = st.columns(2)

        with col1:
            medicamento = st.text_input("Medicamento")
            categoria = st.selectbox(
                "Categoria",
                ["Antibiótico", "Anti-inflamatório", "Vermífugo", "Vacina", "Suplemento", "Curativo", "Hormônio", "Reprodução", "Soro", "Outro"]
            )
            quantidade_compra = st.number_input("Quantidade comprada", min_value=0.0, step=1.0)
            unidade_compra = st.selectbox("Unidade da compra", ["FR", "UN", "CX", "AMP", "L", "mL", "KG", "G", "SC", "Outro"])
            volume_por_unidade = st.number_input(
                "Volume por unidade",
                min_value=0.0,
                step=1.0,
                help="Exemplo: frasco 50 mL = informe 50. Soro 1 litro = informe 1 e unidade controle L."
            )
            unidade_sugerida = sugerir_unidade_controle(medicamento, unidade_compra)
            unidade_controle = st.selectbox(
                "Unidade de controle",
                ["mL", "L"],
                index=1 if unidade_sugerida == "L" else 0
            )

        with col2:
            estoque_convertido = calcular_estoque_convertido(quantidade_compra, volume_por_unidade)
            st.metric("Estoque convertido", f"{estoque_convertido:,.2f} {unidade_controle}".replace(",", "X").replace(".", ",").replace("X", "."))

            estoque_min_controle = st.number_input(f"Estoque mínimo em {unidade_controle}", min_value=0.0, step=1.0)
            preco_total = st.number_input("Valor total da compra", min_value=0.0, step=1.0)
            preco_por_controle = calcular_preco_por_controle(preco_total, estoque_convertido)
            st.metric(f"Custo por {unidade_controle}", moeda(preco_por_controle))

            validade = st.date_input("Validade", format="DD/MM/YYYY")
            fornecedor = st.text_input("Fornecedor")
            obs = st.text_area("Observações")

        if st.button("Salvar Medicamento"):
            c.execute("""
                INSERT INTO farmacia
                (medicamento, categoria, quantidade, unidade, validade, fornecedor,
                 obs, estoque_min, preco, quantidade_compra, unidade_compra,
                 volume_por_unidade, unidade_controle, estoque_convertido,
                 estoque_min_controle, preco_por_controle)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                medicamento, categoria, str(quantidade_compra), unidade_compra, br_data(validade),
                fornecedor, obs, str(estoque_min_controle), str(preco_total),
                str(quantidade_compra), unidade_compra, str(volume_por_unidade),
                unidade_controle, str(estoque_convertido), str(estoque_min_controle),
                str(preco_por_controle)
            ))
            conn.commit()
            st.success("Medicamento cadastrado com estoque convertido!")

    elif aba == "Estoque":
        df = listar_farmacia()

        if not df.empty:
            df["estoque_convertido_num"] = coluna_numerica_segura(df, "estoque_convertido")
            df["preco_por_controle_num"] = coluna_numerica_segura(df, "preco_por_controle")
            df["valor_real_estoque"] = df["estoque_convertido_num"] * df["preco_por_controle_num"]

            total_estoque = df["valor_real_estoque"].sum()
            total_itens = len(df)
            itens_baixos = 0
            if "estoque_min_controle" in df.columns:
                df["estoque_min_controle_num"] = coluna_numerica_segura(df, "estoque_min_controle")
                itens_baixos = len(df[df["estoque_convertido_num"] <= df["estoque_min_controle_num"]])

            col1, col2, col3 = st.columns(3)
            col1.metric("Valor total em estoque", moeda(total_estoque))
            col2.metric("Itens cadastrados", total_itens)
            col3.metric("Itens em alerta", itens_baixos)

            st.markdown("### Ações rápidas")
            col_btn1, col_btn2 = st.columns(2)

            with col_btn1:
                if st.button("🔄 Recalcular volumes pela descrição", use_container_width=True):
                    alterados = recalcular_farmacia_por_descricao(somente_volume_igual_1=True)
                    st.success(f"{alterados} medicamento(s) recalculado(s).")
                    st.rerun()

            with col_btn2:
                st.download_button(
                    "📥 Baixar Estoque Completo",
                    data=gerar_excel(df),
                    file_name="estoque_farmacia_convertido.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

            st.markdown("---")
            st.markdown("### Consulta do estoque")

            busca = st.text_input("Buscar medicamento")
            df_view = df.copy()

            if busca:
                df_view = df_view[df_view["medicamento"].str.contains(busca, case=False, na=False)]

            resumo_cols = ["id", "medicamento", "categoria", "estoque_convertido", "unidade_controle", "preco_por_controle", "valor_real_estoque"]
            resumo_cols = [c0 for c0 in resumo_cols if c0 in df_view.columns]
            st.dataframe(df_view[resumo_cols], use_container_width=True, hide_index=True)

            if not df_view.empty:
                st.markdown("### Detalhe do medicamento")
                df_view["descricao"] = df_view["id"].astype(str) + " - " + df_view["medicamento"].fillna("")
                escolha = st.selectbox("Clique/selecione um medicamento para abrir o detalhe", df_view["descricao"].tolist())
                med_id = escolha.split(" - ")[0]

                med = df[df["id"].astype(str) == str(med_id)].iloc[0]

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Estoque", f"{float(med.get('estoque_convertido') or 0):,.2f} {med.get('unidade_controle') or ''}".replace(",", "X").replace(".", ",").replace("X", "."))
                c2.metric("Volume por unidade", f"{float(med.get('volume_por_unidade') or 0):,.2f} {med.get('unidade_controle') or ''}".replace(",", "X").replace(".", ",").replace("X", "."))
                c3.metric("Custo por unidade controle", moeda(float(med.get("preco_por_controle") or 0)))
                c4.metric("Valor em estoque", moeda(float(med.get("valor_real_estoque") or 0)))

                st.markdown(f"""
                **Medicamento:** {med.get('medicamento', '')}  
                **Categoria:** {med.get('categoria', '')}  
                **Quantidade comprada:** {med.get('quantidade_compra', '')} {med.get('unidade_compra', '')}  
                **Fornecedor:** {med.get('fornecedor', '')}  
                **Validade:** {med.get('validade', '')}  
                **Observações:** {med.get('obs', '')}
                """)

        else:
            st.warning("Nenhum medicamento cadastrado.")

    elif aba == "Alterar Medicamento":
        df = listar_farmacia()

        if df.empty:
            st.warning("Nenhum medicamento cadastrado.")
        else:
            df["descricao"] = df["id"].astype(str) + " - " + df["medicamento"].fillna("")
            escolha = st.selectbox("Escolha o medicamento", df["descricao"].tolist())
            med_id = escolha.split(" - ")[0]

            med = pd.read_sql_query("SELECT * FROM farmacia WHERE id = ?", conn, params=(med_id,)).iloc[0]

            col1, col2 = st.columns(2)

            with col1:
                medicamento = st.text_input("Medicamento", value=str(med.get("medicamento", "") or ""))
                categorias = ["Antibiótico", "Anti-inflamatório", "Vermífugo", "Vacina", "Suplemento", "Curativo", "Hormônio", "Reprodução", "Soro", "Outro"]
                categoria = st.selectbox("Categoria", categorias, index=categorias.index(med["categoria"]) if med.get("categoria") in categorias else len(categorias)-1)

                quantidade_compra = st.number_input("Quantidade comprada", min_value=0.0, step=1.0, value=float(med.get("quantidade_compra") or med.get("quantidade") or 0))
                unidades_compra = ["FR", "UN", "CX", "AMP", "L", "mL", "KG", "G", "SC", "Outro"]
                unidade_atual = med.get("unidade_compra") or med.get("unidade") or "FR"
                unidade_compra = st.selectbox("Unidade da compra", unidades_compra, index=unidades_compra.index(unidade_atual) if unidade_atual in unidades_compra else 0)
                volume_por_unidade = st.number_input("Volume por unidade", min_value=0.0, step=1.0, value=float(med.get("volume_por_unidade") or 1))

                if st.button("🔎 Recalcular volume pela descrição", use_container_width=True):
                    vol, un = extrair_volume_descricao(medicamento)
                    c.execute("""
                        UPDATE farmacia
                        SET volume_por_unidade = ?, unidade_controle = ?
                        WHERE id = ?
                    """, (str(vol), un, str(med_id)))
                    conn.commit()
                    st.success(f"Volume identificado: {vol} {un}.")
                    st.rerun()

                unidade_controle_atual = med.get("unidade_controle") or sugerir_unidade_controle(medicamento, unidade_compra)
                unidades_controle = ["mL", "L"]
                unidade_controle = st.selectbox("Unidade de controle", unidades_controle, index=unidades_controle.index(unidade_controle_atual) if unidade_controle_atual in unidades_controle else 0)

            with col2:
                estoque_convertido = st.number_input(f"Estoque atual em {unidade_controle}", min_value=0.0, step=1.0, value=float(med.get("estoque_convertido") or calcular_estoque_convertido(quantidade_compra, volume_por_unidade)))
                estoque_min_controle = st.number_input(f"Estoque mínimo em {unidade_controle}", min_value=0.0, step=1.0, value=float(med.get("estoque_min_controle") or med.get("estoque_min") or 0))
                preco_total = st.number_input("Valor total da compra/estoque", min_value=0.0, step=1.0, value=float(med.get("preco") or 0))
                preco_por_controle = calcular_preco_por_controle(preco_total, estoque_convertido)
                st.metric(f"Custo por {unidade_controle}", moeda(preco_por_controle))

                validade = st.text_input("Validade", value=str(med.get("validade", "") or ""))
                fornecedor = st.text_input("Fornecedor", value=str(med.get("fornecedor", "") or ""))
                obs = st.text_area("Observações", value=str(med.get("obs", "") or ""))

            colb1, colb2 = st.columns(2)
            with colb1:
                if st.button("💾 Salvar Alterações do Medicamento", use_container_width=True):
                    c.execute("""
                        UPDATE farmacia
                        SET medicamento = ?, categoria = ?, quantidade = ?, unidade = ?,
                            validade = ?, fornecedor = ?, obs = ?, estoque_min = ?,
                            preco = ?, quantidade_compra = ?, unidade_compra = ?,
                            volume_por_unidade = ?, unidade_controle = ?,
                            estoque_convertido = ?, estoque_min_controle = ?,
                            preco_por_controle = ?
                        WHERE id = ?
                    """, (
                        medicamento, categoria, str(quantidade_compra), unidade_compra,
                        validade, fornecedor, obs, str(estoque_min_controle),
                        str(preco_total), str(quantidade_compra), unidade_compra,
                        str(volume_por_unidade), unidade_controle,
                        str(estoque_convertido), str(estoque_min_controle),
                        str(preco_por_controle), str(med_id)
                    ))
                    conn.commit()
                    st.success("Medicamento alterado com sucesso!")
                    st.rerun()

            with colb2:
                confirmar = st.checkbox("Confirmar exclusão deste medicamento")
                if st.button("🗑️ Excluir Medicamento", use_container_width=True):
                    if confirmar:
                        c.execute("DELETE FROM farmacia WHERE id = ?", (med_id,))
                        conn.commit()
                        st.success("Medicamento excluído com sucesso!")
                        st.rerun()
                    else:
                        st.error("Marque a confirmação para excluir.")

    elif aba == "Alertas de Estoque":
        df = listar_farmacia()

        if not df.empty:
            df["estoque_convertido_num"] = coluna_numerica_segura(df, "estoque_convertido")
            df["estoque_min_controle_num"] = coluna_numerica_segura(df, "estoque_min_controle")

            alerta = df[(df["estoque_convertido_num"] <= df["estoque_min_controle_num"]) | (df["estoque_convertido_num"] <= 0)]

            if not alerta.empty:
                st.error("Medicamentos com estoque baixo ou zerado:")
                cols = ["medicamento", "categoria", "estoque_convertido", "unidade_controle", "estoque_min_controle", "fornecedor"]
                st.dataframe(alerta[[c0 for c0 in cols if c0 in alerta.columns]], use_container_width=True)
            else:
                st.success("Nenhum medicamento abaixo do estoque mínimo.")
        else:
            st.warning("Nenhum medicamento cadastrado.")




# =========================================================
# VETERINÁRIO / TRATAMENTOS
# =========================================================

elif op == "Veterinário / Tratamentos":
    titulo_pagina(
        "🩺 Veterinário / Tratamentos",
        "Ficha médica com prescrição, horários de medicação, baixa de estoque e alertas WhatsApp"
    )

    aba = st.radio(
        "Opção",
        ["Nova Ficha Médica", "Histórico de Fichas", "Medicações Agendadas"],
        horizontal=True
    )

    animais = listar_animais()
    farmacia = listar_farmacia()
    funcionarios = pd.read_sql_query(
        "SELECT * FROM funcionarios WHERE nome IS NOT NULL AND nome != '' AND status = 'Ativo'",
        conn
    )

    # -----------------------------------------------------
    # NOVA FICHA MÉDICA
    # -----------------------------------------------------
    if aba == "Nova Ficha Médica":
        if animais.empty:
            st.warning("Cadastre um animal primeiro.")
        else:
            animais["descricao"] = animais["nome"] + " - " + animais["tipo"]
            escolha = st.selectbox("Animal", animais["descricao"].tolist())

            animal_nome = escolha.split(" - ")[0]
            animal_tipo = escolha.split(" - ")[1]

            st.markdown("### 1. Dados do atendimento")

            col1, col2 = st.columns(2)

            with col1:
                data = st.date_input("Data do atendimento", format="DD/MM/YYYY")
                motivo = st.text_input("Motivo do atendimento")
                diagnostico = st.text_area("Diagnóstico")
                tratamento_indicado = st.text_area("Tratamento / conduta geral")

            with col2:
                veterinario = st.text_input("Veterinário / Responsável técnico")
                retorno = st.date_input("Retorno previsto", format="DD/MM/YYYY")
                obs_ficha = st.text_area("Observações gerais da ficha")

            st.markdown("---")
            st.markdown("### 2. Prescrição / Medicações")

            if "medicacoes_ficha_temp" not in st.session_state:
                st.session_state.medicacoes_ficha_temp = []

            medicamentos_lista = ["Nenhum"]
            if not farmacia.empty:
                medicamentos_lista += farmacia["medicamento"].dropna().tolist()

            colm1, colm2 = st.columns(2)

            with colm1:
                medicamento = st.selectbox("Medicamento", medicamentos_lista)

                unidade_padrao = "mL"
                estoque_atual = 0.0
                preco_unitario = 0.0

                if medicamento != "Nenhum":
                    med_df = pd.read_sql_query(
                        "SELECT * FROM farmacia WHERE medicamento = ?",
                        conn,
                        params=(medicamento,)
                    )

                    if not med_df.empty:
                        med_row = med_df.iloc[0]
                        unidade_padrao = med_row.get("unidade_controle", "") or med_row.get("unidade", "") or "mL"

                        if med_row.get("estoque_convertido", "") not in [None, ""]:
                            estoque_atual = float(med_row.get("estoque_convertido") or 0)
                            preco_unitario = float(med_row.get("preco_por_controle") or 0)
                        else:
                            estoque_atual = float(med_row.get("quantidade") or 0)
                            preco_unitario = float(med_row.get("preco") or 0)

                        st.info(
                            (
                                f"Estoque atual: {estoque_atual:,.2f} {unidade_padrao} | "
                                f"Custo por {unidade_padrao}: {moeda(preco_unitario)}"
                            ).replace(",", "X").replace(".", ",").replace("X", ".")
                        )

                quantidade = st.number_input(
                    f"Quantidade por aplicação ({unidade_padrao})",
                    min_value=0.0,
                    step=1.0
                )
                unidade = st.text_input("Unidade", value=unidade_padrao)
                dosagem = st.text_input("Dosagem / orientação")

            with colm2:
                data_medicacao = st.date_input("Data da aplicação", value=data, format="DD/MM/YYYY")
                hora_medicacao = st.time_input("Hora da aplicação")

                funcionario_nome = ""
                telefone_funcionario = ""

                if funcionarios.empty:
                    st.warning("Cadastre funcionário ativo para gerar alerta WhatsApp.")
                else:
                    funcionarios["descricao"] = funcionarios["nome"] + " - " + funcionarios["cargo"].fillna("")
                    escolha_func = st.selectbox("Funcionário responsável", funcionarios["descricao"].tolist())
                    funcionario_nome = escolha_func.split(" - ")[0]
                    func = funcionarios[funcionarios["nome"] == funcionario_nome].iloc[0]
                    telefone_funcionario = str(func["telefone"] or "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

                custo_item = quantidade * preco_unitario
                st.metric("Custo desta aplicação", moeda(custo_item))

            if st.button("➕ Adicionar medicação à ficha", use_container_width=True):
                if medicamento == "Nenhum":
                    st.error("Selecione um medicamento.")
                elif quantidade <= 0:
                    st.error("Informe a quantidade.")
                else:
                    data_hora_medicacao = datetime.combine(data_medicacao, hora_medicacao)

                    mensagem_alerta = (
                        f"Olá, {funcionario_nome}!\\n\\n"
                        f"🚨 Lembrete de medicação - Rancho Recanto Verde\\n\\n"
                        f"Animal: {animal_nome}\\n"
                        f"Medicamento: {medicamento}\\n"
                        f"Quantidade: {quantidade} {unidade}\\n"
                        f"Dosagem/orientação: {dosagem}\\n"
                        f"Data e hora: {data_hora_medicacao.strftime('%d/%m/%Y %H:%M')}\\n\\n"
                        f"Favor confirmar a aplicação no sistema."
                    )

                    st.session_state.medicacoes_ficha_temp.append({
                        "animal": animal_nome,
                        "tipo_animal": animal_tipo,
                        "medicamento": medicamento,
                        "quantidade": quantidade,
                        "unidade": unidade,
                        "dosagem": dosagem,
                        "data_hora": data_hora_medicacao.strftime("%d/%m/%Y %H:%M"),
                        "funcionario": funcionario_nome,
                        "telefone": telefone_funcionario,
                        "mensagem": mensagem_alerta,
                        "preco_unitario": preco_unitario,
                        "custo_total": custo_item
                    })
                    st.success("Medicação adicionada à ficha.")

            if st.session_state.medicacoes_ficha_temp:
                st.markdown("### 3. Medicações adicionadas")
                df_temp = pd.DataFrame(st.session_state.medicacoes_ficha_temp)
                st.dataframe(df_temp, use_container_width=True, hide_index=True)

                custo_total_ficha = sum(float(x.get("custo_total", 0) or 0) for x in st.session_state.medicacoes_ficha_temp)
                st.metric("Custo total da ficha", moeda(custo_total_ficha))

                colsave, colclear = st.columns(2)

                with colclear:
                    if st.button("🧹 Limpar medicações da ficha", use_container_width=True):
                        st.session_state.medicacoes_ficha_temp = []
                        st.rerun()

                with colsave:
                    if st.button("💾 Salvar Ficha Médica e Baixar Estoque", use_container_width=True):
                        # Valida estoque antes de salvar
                        erros_estoque = []
                        for item in st.session_state.medicacoes_ficha_temp:
                            med_df = pd.read_sql_query(
                                "SELECT * FROM farmacia WHERE medicamento = ?",
                                conn,
                                params=(item["medicamento"],)
                            )

                            if med_df.empty:
                                erros_estoque.append(f"{item['medicamento']}: não encontrado.")
                            else:
                                med_row = med_df.iloc[0]
                                if med_row.get("estoque_convertido", "") not in [None, ""]:
                                    estoque_disp = float(med_row.get("estoque_convertido") or 0)
                                else:
                                    estoque_disp = float(med_row.get("quantidade") or 0)

                                if float(item["quantidade"]) > estoque_disp:
                                    erros_estoque.append(
                                        f"{item['medicamento']}: estoque insuficiente. Disponível {estoque_disp} {item['unidade']}."
                                    )

                        if erros_estoque:
                            for erro in erros_estoque:
                                st.error(erro)
                            st.stop()

                        c.execute("""
                            INSERT INTO fichas_medicas
                            (animal, tipo_animal, data_atendimento, motivo,
                             diagnostico, tratamento_indicado, veterinario,
                             retorno, status, custo_total, obs)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            animal_nome,
                            animal_tipo,
                            br_data(data),
                            motivo,
                            diagnostico,
                            tratamento_indicado,
                            veterinario,
                            br_data(retorno),
                            "Aberta",
                            str(custo_total_ficha),
                            obs_ficha
                        ))

                        ficha_id = c.lastrowid

                        # Salva cada medicação, agenda alerta e baixa estoque
                        for item in st.session_state.medicacoes_ficha_temp:
                            ok, nova_qtd, preco_unitario_final, erro = baixar_estoque(
                                item["medicamento"],
                                float(item["quantidade"])
                            )

                            if not ok:
                                st.error(erro)
                                st.stop()

                            custo_item_final = float(item["quantidade"]) * float(preco_unitario_final or item["preco_unitario"])

                            c.execute("""
                                INSERT INTO ficha_medicacoes
                                (ficha_id, animal, tipo_animal, medicamento, quantidade,
                                 unidade, dosagem, data_hora, funcionario, telefone,
                                 mensagem, status, alerta_gerado, data_alerta,
                                 preco_unitario, custo_total, obs)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                str(ficha_id),
                                item["animal"],
                                item["tipo_animal"],
                                item["medicamento"],
                                str(item["quantidade"]),
                                item["unidade"],
                                item["dosagem"],
                                item["data_hora"],
                                item["funcionario"],
                                item["telefone"],
                                item["mensagem"],
                                "Agendada",
                                "Não",
                                "",
                                str(preco_unitario_final),
                                str(custo_item_final),
                                ""
                            ))

                            c.execute("""
                                INSERT INTO medicacoes_agendadas
                                (animal, tipo_animal, medicamento, dosagem, data_hora,
                                 funcionario, telefone, mensagem, status, alerta_gerado,
                                 data_alerta, obs)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                item["animal"],
                                item["tipo_animal"],
                                item["medicamento"],
                                f"{item['quantidade']} {item['unidade']} - {item['dosagem']}",
                                item["data_hora"],
                                item["funcionario"],
                                item["telefone"],
                                item["mensagem"],
                                "Agendada",
                                "Não",
                                "",
                                f"Ficha médica nº {ficha_id}"
                            ))

                            # Mantém compatibilidade com histórico antigo
                            c.execute("""
                                INSERT INTO tratamentos
                                (animal, tipo, data, motivo, diagnostico, tratamento,
                                 medicamento, quantidade_usada, unidade, dosagem,
                                 preco_unitario, custo_total, veterinario, retorno,
                                 funcionario_responsavel, telefone_funcionario,
                                 data_hora_medicacao, gerar_alerta_whatsapp, obs)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                animal_nome,
                                animal_tipo,
                                br_data(data),
                                motivo,
                                diagnostico,
                                tratamento_indicado,
                                item["medicamento"],
                                str(item["quantidade"]),
                                item["unidade"],
                                item["dosagem"],
                                str(preco_unitario_final),
                                str(custo_item_final),
                                veterinario,
                                br_data(retorno),
                                item["funcionario"],
                                item["telefone"],
                                item["data_hora"],
                                "Sim",
                                f"Ficha médica nº {ficha_id}"
                            ))

                        conn.commit()
                        st.session_state.medicacoes_ficha_temp = []
                        st.success(f"Ficha médica nº {ficha_id} salva com sucesso, estoque baixado e alertas agendados.")
                        st.rerun()
            else:
                st.info("Adicione uma ou mais medicações antes de salvar a ficha.")

    # -----------------------------------------------------
    # HISTÓRICO DE FICHAS
    # -----------------------------------------------------
    elif aba == "Histórico de Fichas":
        fichas = pd.read_sql_query("SELECT * FROM fichas_medicas WHERE animal IS NOT NULL ORDER BY id DESC", conn)

        if fichas.empty:
            st.warning("Nenhuma ficha médica registrada.")
        else:
            st.dataframe(fichas, use_container_width=True, hide_index=True)

            fichas["descricao"] = fichas["id"].astype(str) + " - " + fichas["animal"].fillna("") + " - " + fichas["data_atendimento"].fillna("")
            escolha = st.selectbox("Abrir detalhe da ficha", fichas["descricao"].tolist())
            ficha_id = escolha.split(" - ")[0]

            ficha = fichas[fichas["id"].astype(str) == ficha_id].iloc[0]
            meds = pd.read_sql_query("SELECT * FROM ficha_medicacoes WHERE ficha_id = ? ORDER BY data_hora", conn, params=(ficha_id,))

            st.markdown(f"### Ficha médica nº {ficha_id}")
            st.write(f"**Animal:** {ficha.get('animal', '')}")
            st.write(f"**Data:** {ficha.get('data_atendimento', '')}")
            st.write(f"**Motivo:** {ficha.get('motivo', '')}")
            st.write(f"**Diagnóstico:** {ficha.get('diagnostico', '')}")
            st.write(f"**Tratamento:** {ficha.get('tratamento_indicado', '')}")
            st.write(f"**Veterinário:** {ficha.get('veterinario', '')}")
            st.metric("Custo total da ficha", moeda(float(ficha.get("custo_total") or 0)))

            st.markdown("### Medicações da ficha")
            if not meds.empty:
                st.dataframe(meds, use_container_width=True, hide_index=True)
            else:
                st.info("Nenhuma medicação vinculada.")

            st.download_button(
                "📥 Baixar fichas médicas",
                data=gerar_excel(fichas),
                file_name="fichas_medicas.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    # -----------------------------------------------------
    # MEDICAÇÕES AGENDADAS
    # -----------------------------------------------------
    elif aba == "Medicações Agendadas":
        meds = pd.read_sql_query("SELECT * FROM ficha_medicacoes WHERE medicamento IS NOT NULL ORDER BY data_hora", conn)

        if meds.empty:
            st.warning("Nenhuma medicação agendada.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                filtro_status = st.selectbox("Status", ["Todos", "Agendada", "Aplicada", "Cancelada"])
            with col2:
                filtro_animal = st.selectbox("Animal", ["Todos"] + sorted(meds["animal"].dropna().unique().tolist()))

            view = meds.copy()
            if filtro_status != "Todos":
                view = view[view["status"] == filtro_status]
            if filtro_animal != "Todos":
                view = view[view["animal"] == filtro_animal]

            st.dataframe(view, use_container_width=True, hide_index=True)

            if not view.empty:
                view["descricao"] = view["id"].astype(str) + " - " + view["animal"].fillna("") + " - " + view["medicamento"].fillna("") + " - " + view["data_hora"].fillna("")
                escolha = st.selectbox("Selecionar medicação", view["descricao"].tolist())
                med_id = escolha.split(" - ")[0]
                med = view[view["id"].astype(str) == med_id].iloc[0]

                colb1, colb2 = st.columns(2)

                with colb1:
                    if st.button("✅ Marcar como aplicada", use_container_width=True):
                        c.execute("UPDATE ficha_medicacoes SET status = ? WHERE id = ?", ("Aplicada", med_id))
                        c.execute("""
                            UPDATE medicacoes_agendadas
                            SET status = ?
                            WHERE animal = ? AND medicamento = ? AND data_hora = ?
                        """, ("Aplicada", med["animal"], med["medicamento"], med["data_hora"]))
                        conn.commit()
                        st.success("Medicação marcada como aplicada.")
                        st.rerun()

                with colb2:
                    if st.button("🚫 Cancelar medicação", use_container_width=True):
                        c.execute("UPDATE ficha_medicacoes SET status = ? WHERE id = ?", ("Cancelada", med_id))
                        c.execute("""
                            UPDATE medicacoes_agendadas
                            SET status = ?
                            WHERE animal = ? AND medicamento = ? AND data_hora = ?
                        """, ("Cancelada", med["animal"], med["medicamento"], med["data_hora"]))
                        conn.commit()
                        st.success("Medicação cancelada.")
                        st.rerun()


# =========================================================
# REPRODUÇÃO / EMBRIÕES
# =========================================================

elif op == "Reprodução / Embriões":
    titulo_pagina("🧬 Reprodução / Embriões", "Controle de doadoras, inseminações, receptoras e previsão de parto")

    aba = st.radio(
        "Opção",
        ["Éguas Doadoras / Inseminadas", "Receptoras", "Alertas Reprodutivos", "Histórico Reprodutivo"],
        horizontal=True
    )

    animais = listar_animais()
    equinos_femeas = animais[(animais["tipo"] == "Equino") & (animais["sexo"] == "Fêmea")] if not animais.empty else pd.DataFrame()

    if aba == "Éguas Doadoras / Inseminadas":
        if equinos_femeas.empty:
            st.warning("Cadastre éguas fêmeas do tipo Equino primeiro.")
        else:
            egua = st.selectbox("Égua doadora / inseminada", equinos_femeas["nome"].tolist())

            col1, col2 = st.columns(2)
            with col1:
                garanhao = st.text_input("Garanhão / sêmen utilizado")
                data_inseminacao = st.date_input("Data da inseminação", format="DD/MM/YYYY")
                data_prevista_lavagem = st.date_input("Data prevista da lavagem", format="DD/MM/YYYY")
                data_lavagem = st.date_input("Data da lavagem", format="DD/MM/YYYY")
                status = st.selectbox("Status", ["Inseminada", "Lavagem prevista", "Lavada", "Sem embrião", "Embrião coletado", "Cancelado"])
            with col2:
                protocolo = st.text_area("Protocolo")
                dosagens = st.text_area("Dosagens")
                resultado_lavagem = st.text_area("Resultado da lavagem")
                embrioes_coletados = st.number_input("Quantidade de embriões coletados", min_value=0, step=1)
                obs = st.text_area("Observações")

            if st.button("Salvar Doadora / Inseminação"):
                c.execute("""
                    INSERT INTO doadoras
                    (egua_doadora, garanhao, data_inseminacao, protocolo, dosagens,
                     data_prevista_lavagem, data_lavagem, resultado_lavagem,
                     embrioes_coletados, status, obs)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    egua, garanhao, br_data(data_inseminacao), protocolo, dosagens,
                    br_data(data_prevista_lavagem), br_data(data_lavagem),
                    resultado_lavagem, str(embrioes_coletados), status, obs
                ))
                conn.commit()
                st.success("Controle da doadora salvo com sucesso!")

    elif aba == "Receptoras":
        if equinos_femeas.empty:
            st.warning("Cadastre receptoras fêmeas do tipo Equino primeiro.")
        else:
            receptora = st.selectbox("Receptora", equinos_femeas["nome"].tolist())
            doadoras = pd.read_sql_query("SELECT * FROM doadoras WHERE egua_doadora IS NOT NULL", conn)

            col1, col2 = st.columns(2)
            with col1:
                if not doadoras.empty:
                    doadora = st.selectbox("Égua doadora", doadoras["egua_doadora"].dropna().unique().tolist())
                else:
                    doadora = st.text_input("Égua doadora")
                garanhao = st.text_input("Garanhão")
                cruzamento = st.text_input("Cruzamento no ventre")
                data_transferencia = st.date_input("Data da transferência do embrião", format="DD/MM/YYYY")
                previsao_parto = st.date_input("Previsão de parto", format="DD/MM/YYYY")
                confirmacao_prenhez = st.date_input("Confirmação de prenhez", format="DD/MM/YYYY")
            with col2:
                protocolo = st.text_area("Protocolo")
                dosagens = st.text_area("Dosagens")
                status = st.selectbox("Status", ["Aguardando confirmação", "Prenhe", "Vazia", "Perdeu", "Pariu", "Cancelado"])
                obs = st.text_area("Observações")

            if st.button("Salvar Receptora"):
                if not cruzamento:
                    cruzamento = f"{doadora} x {garanhao}"

                c.execute("""
                    INSERT INTO receptoras
                    (receptora, egua_doadora, garanhao, cruzamento, data_transferencia,
                     dosagens, protocolo, previsao_parto, confirmacao_prenhez, status, obs)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    receptora, doadora, garanhao, cruzamento, br_data(data_transferencia),
                    dosagens, protocolo, br_data(previsao_parto),
                    br_data(confirmacao_prenhez), status, obs
                ))
                conn.commit()
                st.success("Controle da receptora salvo com sucesso!")

    elif aba == "Alertas Reprodutivos":
        doadoras = pd.read_sql_query("SELECT * FROM doadoras WHERE egua_doadora IS NOT NULL", conn)
        receptoras = pd.read_sql_query("SELECT * FROM receptoras WHERE receptora IS NOT NULL", conn)

        st.markdown("### Alertas de Lavagem")
        if not doadoras.empty:
            doadoras["status_lavagem"] = doadoras["data_prevista_lavagem"].apply(lambda x: status_data(x, 7))
            alertas_lavagem = doadoras[doadoras["status_lavagem"].isin(["VENCIDO", "PRÓXIMO"])]
            if not alertas_lavagem.empty:
                st.warning("⚠️ Lavagens vencidas ou próximas.")
                st.dataframe(alertas_lavagem, use_container_width=True)
            else:
                st.success("Nenhuma lavagem próxima.")
        else:
            st.info("Nenhuma doadora registrada.")

        st.markdown("### Alertas de Parto")
        if not receptoras.empty:
            receptoras["status_parto"] = receptoras["previsao_parto"].apply(lambda x: status_data(x, 30))
            alertas_parto = receptoras[receptoras["status_parto"].isin(["VENCIDO", "PRÓXIMO"])]
            if not alertas_parto.empty:
                st.warning("⚠️ Partos vencidos ou próximos.")
                st.dataframe(alertas_parto, use_container_width=True)
            else:
                st.success("Nenhum parto próximo.")
        else:
            st.info("Nenhuma receptora registrada.")

    elif aba == "Histórico Reprodutivo":
        st.markdown("### Éguas Doadoras / Inseminadas")
        doadoras = pd.read_sql_query("SELECT * FROM doadoras WHERE egua_doadora IS NOT NULL", conn)
        st.dataframe(doadoras, use_container_width=True)

        st.markdown("### Receptoras")
        receptoras = pd.read_sql_query("SELECT * FROM receptoras WHERE receptora IS NOT NULL", conn)
        st.dataframe(receptoras, use_container_width=True)


# =========================================================
# VENDAS DE ANIMAIS
# =========================================================

elif op == "Vendas de Animais":
    titulo_pagina("💰 Vendas de Animais", "Negociação, comprador, contrato e controle de recebimentos")

    aba = st.radio(
        "Opção",
        ["Cadastrar Venda", "Recebimentos", "Histórico de Vendas", "Contrato PDF"],
        horizontal=True
    )

    animais = listar_animais(somente_ativos=True)

    if aba == "Cadastrar Venda":
        if animais.empty:
            st.warning("Nenhum animal ativo disponível para venda.")
        else:
            animais["descricao"] = animais["nome"] + " - " + animais["tipo"]
            escolha = st.selectbox("Animal vendido", animais["descricao"].tolist())
            animal_nome = escolha.split(" - ")[0]
            animal_tipo = escolha.split(" - ")[1]

            col1, col2 = st.columns(2)

            with col1:
                data_venda = st.date_input("Data da venda", format="DD/MM/YYYY")
                valor_negociado = st.number_input("Valor negociado", min_value=0.0, step=100.0)
                desconto = st.number_input("Desconto", min_value=0.0, step=100.0)
                valor_final = valor_negociado - desconto
                st.metric("Valor final", moeda(valor_final))
                forma_pagamento = st.selectbox("Forma de pagamento", ["À vista", "Parcelado", "PIX", "Transferência", "Boleto", "Dinheiro", "Outro"])
                parcelas = st.number_input("Quantidade de parcelas", min_value=1, step=1)
                status_venda = st.selectbox("Status", ["Em negociação", "Vendido", "Cancelado"])

            with col2:
                comprador_nome = st.text_input("Comprador - Nome completo")
                comprador_cpf_cnpj = st.text_input("Comprador - CPF/CNPJ")
                comprador_telefone = st.text_input("Comprador - Telefone")
                comprador_email = st.text_input("Comprador - E-mail")
                comprador_endereco = st.text_area("Comprador - Endereço completo")
                obs = st.text_area("Observações da negociação")

            if st.button("Salvar Venda e Gerar Parcelas"):
                c.execute("""
                    INSERT INTO vendas
                    (animal, tipo, data_venda, valor_negociado, desconto, valor_final,
                     forma_pagamento, parcelas, status_venda, comprador_nome,
                     comprador_cpf_cnpj, comprador_telefone, comprador_email,
                     comprador_endereco, obs)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    animal_nome, animal_tipo, br_data(data_venda), str(valor_negociado),
                    str(desconto), str(valor_final), forma_pagamento, str(parcelas),
                    status_venda, comprador_nome, comprador_cpf_cnpj, comprador_telefone,
                    comprador_email, comprador_endereco, obs
                ))
                venda_id = c.lastrowid

                valor_parcela = valor_final / parcelas if parcelas else valor_final
                data_base = data_venda

                for i in range(1, int(parcelas) + 1):
                    venc = data_base + timedelta(days=30 * (i - 1))
                    c.execute("""
                        INSERT INTO recebimentos
                        (venda_id, animal, comprador, parcela, vencimento, valor,
                         data_pagamento, status, obs)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        str(venda_id), animal_nome, comprador_nome, str(i),
                        br_data(venc), str(valor_parcela), "", "Em aberto", ""
                    ))

                if status_venda == "Vendido":
                    c.execute("UPDATE animais SET status = ? WHERE nome = ?", ("Vendido", animal_nome))

                conn.commit()
                st.success("Venda salva e parcelas geradas com sucesso!")

    elif aba == "Recebimentos":
        df = pd.read_sql_query("SELECT * FROM recebimentos WHERE animal IS NOT NULL", conn)

        if not df.empty:
            df["valor_num"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0)

            st.metric("Total em aberto", moeda(df[df["status"] != "Pago"]["valor_num"].sum()))
            st.metric("Total recebido", moeda(df[df["status"] == "Pago"]["valor_num"].sum()))

            st.dataframe(df, use_container_width=True)

            st.markdown("### Dar baixa em parcela")
            ids = df["id"].astype(str).tolist()
            parcela_id = st.selectbox("Escolha o ID da parcela", ids)

            data_pagamento = st.date_input("Data de pagamento", format="DD/MM/YYYY")
            obs = st.text_area("Observação do recebimento")

            if st.button("Marcar como Pago"):
                c.execute("""
                    UPDATE recebimentos
                    SET status = ?, data_pagamento = ?, obs = ?
                    WHERE id = ?
                """, ("Pago", br_data(data_pagamento), obs, parcela_id))
                conn.commit()
                st.success("Parcela marcada como paga.")
        else:
            st.warning("Nenhum recebimento cadastrado.")

    elif aba == "Histórico de Vendas":
        df = pd.read_sql_query("SELECT * FROM vendas WHERE animal IS NOT NULL", conn)

        if not df.empty:
            st.dataframe(df, use_container_width=True)
            st.download_button(
                "📥 Baixar Vendas",
                data=gerar_excel(df),
                file_name="historico_vendas.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("Nenhuma venda cadastrada.")

    elif aba == "Contrato PDF":
        vendas = pd.read_sql_query("SELECT * FROM vendas WHERE animal IS NOT NULL", conn)

        if vendas.empty:
            st.warning("Cadastre uma venda primeiro.")
        else:
            vendas["descricao"] = vendas["id"].astype(str) + " - " + vendas["animal"] + " - " + vendas["comprador_nome"]
            esc = st.selectbox("Escolha a venda", vendas["descricao"].tolist())
            venda_id = esc.split(" - ")[0]
            venda = pd.read_sql_query("SELECT * FROM vendas WHERE id = ?", conn, params=(venda_id,)).iloc[0]

            if st.button("Gerar Contrato PDF"):
                buffer = BytesIO()
                pdf = canvas.Canvas(buffer, pagesize=letter)
                largura, altura = letter

                if os.path.exists(LOGO):
                    pdf.drawImage(LOGO, 140, 700, width=320, height=90, preserveAspectRatio=True, mask="auto")

                y = 660
                pdf.setFont("Helvetica-Bold", 14)
                pdf.drawCentredString(largura / 2, y, "CONTRATO DE COMPRA E VENDA DE ANIMAL")
                y -= 35

                pdf.setFont("Helvetica", 10)
                linhas = [
                    "Pelo presente instrumento particular, as partes ajustam a compra e venda do animal abaixo identificado.",
                    "",
                    f"Animal: {venda['animal']} | Tipo: {venda['tipo']}",
                    f"Data da venda: {venda['data_venda']}",
                    "",
                    "COMPRADOR:",
                    f"Nome: {venda['comprador_nome']}",
                    f"CPF/CNPJ: {venda['comprador_cpf_cnpj']}",
                    f"Telefone: {venda['comprador_telefone']}",
                    f"E-mail: {venda['comprador_email']}",
                    f"Endereço: {venda['comprador_endereco']}",
                    "",
                    "CONDIÇÕES DA NEGOCIAÇÃO:",
                    f"Valor negociado: {moeda(venda['valor_negociado'])}",
                    f"Desconto: {moeda(venda['desconto'])}",
                    f"Valor final: {moeda(venda['valor_final'])}",
                    f"Forma de pagamento: {venda['forma_pagamento']}",
                    f"Quantidade de parcelas: {venda['parcelas']}",
                    "",
                    "CLÁUSULAS BÁSICAS:",
                    "1. O vendedor declara estar realizando a venda do animal identificado acima.",
                    "2. O comprador declara ter ciência das condições físicas e sanitárias do animal.",
                    "3. A posse do animal será transferida conforme acordo entre as partes.",
                    "4. O não pagamento das parcelas poderá implicar cobrança e demais medidas cabíveis.",
                    "5. As partes elegem o foro competente para dirimir eventuais controvérsias.",
                    "",
                    f"Observações: {venda['obs']}",
                    "",
                    "Local e data: _______________________________________________",
                    "",
                    "Vendedor: _________________________________________________",
                    "",
                    "Comprador: ________________________________________________",
                ]

                for linha in linhas:
                    pdf.drawString(50, y, str(linha)[:110])
                    y -= 16
                    if y < 60:
                        pdf.showPage()
                        y = 750
                        pdf.setFont("Helvetica", 10)

                pdf.save()

                st.download_button(
                    "📄 Baixar Contrato",
                    data=buffer.getvalue(),
                    file_name=f"contrato_{venda['animal']}.pdf",
                    mime="application/pdf"
                )


# =========================================================
# FUNCIONÁRIOS
# =========================================================

elif op == "Funcionários":
    titulo_pagina("👥 Funcionários", "Cadastro completo da equipe do haras")

    aba = st.radio(
        "Opção",
        ["Cadastrar Funcionário", "Funcionários Cadastrados", "Alterar Funcionário"],
        horizontal=True
    )

    if aba == "Cadastrar Funcionário":
        col1, col2 = st.columns(2)

        with col1:
            nome = st.text_input("Nome completo")
            cpf = st.text_input("CPF")
            rg = st.text_input("RG")
            telefone = st.text_input("Telefone / WhatsApp com DDD")
            email = st.text_input("E-mail")
            endereco = st.text_area("Endereço completo")

        with col2:
            cargo = st.text_input("Cargo / Função")
            setor = st.selectbox("Setor", ["Operacional", "Veterinário", "Financeiro", "Administrativo", "Reprodução", "Outro"])
            salario = st.number_input("Salário", min_value=0.0, step=100.0)
            data_admissao = st.date_input("Data de admissão", format="DD/MM/YYYY")
            status = st.selectbox("Status", ["Ativo", "Afastado", "Desligado", "Férias", "Outro"])
            documentos = st.text_area("Documentos / observações de documentos")
            obs = st.text_area("Observações gerais")

        if st.button("Salvar Funcionário"):
            c.execute("""
                INSERT INTO funcionarios
                (nome, cpf, rg, telefone, email, endereco, cargo, setor,
                 salario, data_admissao, status, documentos, obs)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                nome, cpf, rg, telefone, email, endereco, cargo, setor,
                str(salario), br_data(data_admissao), status, documentos, obs
            ))
            conn.commit()
            st.success("Funcionário cadastrado com sucesso!")

    elif aba == "Funcionários Cadastrados":
        df = pd.read_sql_query("SELECT * FROM funcionarios WHERE nome IS NOT NULL AND nome != ''", conn)

        if not df.empty:
            col1, col2 = st.columns(2)

            with col1:
                filtro_status = st.selectbox("Filtrar por status", ["Todos", "Ativo", "Afastado", "Desligado", "Férias", "Outro"])

            with col2:
                filtro_setor = st.selectbox("Filtrar por setor", ["Todos", "Operacional", "Veterinário", "Financeiro", "Administrativo", "Reprodução", "Outro"])

            df_view = df.copy()

            if filtro_status != "Todos":
                df_view = df_view[df_view["status"] == filtro_status]

            if filtro_setor != "Todos":
                df_view = df_view[df_view["setor"] == filtro_setor]

            if not df_view.empty:
                df_view["salario_num"] = pd.to_numeric(df_view["salario"], errors="coerce").fillna(0)
                st.metric("Folha mensal filtrada", moeda(df_view["salario_num"].sum()))

            st.dataframe(df_view, use_container_width=True)

            st.download_button(
                "📥 Baixar Funcionários",
                data=gerar_excel(df_view),
                file_name="funcionarios_rancho_recanto_verde.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("Nenhum funcionário cadastrado.")

    elif aba == "Alterar Funcionário":
        df = pd.read_sql_query("SELECT * FROM funcionarios WHERE nome IS NOT NULL AND nome != ''", conn)

        if df.empty:
            st.warning("Nenhum funcionário cadastrado.")
        else:
            df["descricao"] = df["id"].astype(str) + " - " + df["nome"].fillna("") + " - " + df["cargo"].fillna("")
            escolha = st.selectbox("Escolha o funcionário", df["descricao"].tolist())
            funcionario_id = escolha.split(" - ")[0]

            funcionario = pd.read_sql_query(
                "SELECT * FROM funcionarios WHERE id = ?",
                conn,
                params=(funcionario_id,)
            ).iloc[0]

            col1, col2 = st.columns(2)

            with col1:
                nome = st.text_input("Nome completo", value=str(funcionario.get("nome", "") or ""))
                cpf = st.text_input("CPF", value=str(funcionario.get("cpf", "") or ""))
                rg = st.text_input("RG", value=str(funcionario.get("rg", "") or ""))
                telefone = st.text_input("Telefone / WhatsApp com DDD", value=str(funcionario.get("telefone", "") or ""))
                email = st.text_input("E-mail", value=str(funcionario.get("email", "") or ""))
                endereco = st.text_area("Endereço completo", value=str(funcionario.get("endereco", "") or ""))

            with col2:
                cargo = st.text_input("Cargo / Função", value=str(funcionario.get("cargo", "") or ""))
                setores = ["Operacional", "Veterinário", "Financeiro", "Administrativo", "Reprodução", "Outro"]
                setor = st.selectbox(
                    "Setor",
                    setores,
                    index=setores.index(funcionario["setor"]) if funcionario.get("setor") in setores else 0
                )
                salario = st.number_input(
                    "Salário",
                    min_value=0.0,
                    step=100.0,
                    value=float(funcionario.get("salario") or 0)
                )
                data_admissao = st.text_input("Data de admissão", value=str(funcionario.get("data_admissao", "") or ""))
                status_opcoes = ["Ativo", "Afastado", "Desligado", "Férias", "Outro"]
                status = st.selectbox(
                    "Status",
                    status_opcoes,
                    index=status_opcoes.index(funcionario["status"]) if funcionario.get("status") in status_opcoes else 0
                )
                documentos = st.text_area("Documentos / observações de documentos", value=str(funcionario.get("documentos", "") or ""))
                obs = st.text_area("Observações gerais", value=str(funcionario.get("obs", "") or ""))

            col_btn1, col_btn2 = st.columns(2)

            with col_btn1:
                if st.button("💾 Salvar Alterações do Funcionário", use_container_width=True):
                    c.execute("""
                        UPDATE funcionarios
                        SET nome = ?, cpf = ?, rg = ?, telefone = ?, email = ?,
                            endereco = ?, cargo = ?, setor = ?, salario = ?,
                            data_admissao = ?, status = ?, documentos = ?, obs = ?
                        WHERE id = ?
                    """, (
                        nome, cpf, rg, telefone, email,
                        endereco, cargo, setor, str(salario),
                        data_admissao, status, documentos, obs,
                        funcionario_id
                    ))
                    conn.commit()
                    st.success("Funcionário alterado com sucesso!")
                    st.rerun()

            with col_btn2:
                confirmar = st.checkbox("Confirmar exclusão deste funcionário")
                if st.button("🗑️ Excluir Funcionário", use_container_width=True):
                    if confirmar:
                        c.execute("DELETE FROM funcionarios WHERE id = ?", (funcionario_id,))
                        conn.commit()
                        st.success("Funcionário excluído com sucesso!")
                        st.rerun()
                    else:
                        st.error("Marque a confirmação para excluir.")



# =========================================================
# ALERTAS WHATSAPP
# =========================================================

elif op == "Alertas WhatsApp":
    titulo_pagina("📲 Alertas WhatsApp", "Envio profissional via Twilio e alternativa pelo WhatsApp Web")

    funcionarios = pd.read_sql_query(
        "SELECT * FROM funcionarios WHERE nome IS NOT NULL AND nome != '' AND status = 'Ativo'",
        conn
    )

    if twilio_configurado():
        st.success("Twilio configurado. Envio real pelo WhatsApp habilitado.")
    else:
        st.warning("Twilio ainda não configurado. O botão de envio pelo Twilio ficará indisponível.")
        st.caption("Configure em Manage app > Settings > Secrets: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN e TWILIO_WHATSAPP_FROM.")

    aba = st.radio(
        "Opção",
        ["Agendar Medicação", "Alertas de Medicação 1h Antes", "Enviar Alerta Manual", "Histórico de Alertas", "Configuração Twilio"],
        horizontal=True
    )

    if aba == "Configuração Twilio":
        st.markdown("### Configuração Twilio")
        st.info("No Streamlit Cloud, vá em Manage app > Settings > Secrets e cadastre as variáveis abaixo.")
        st.code("""
TWILIO_ACCOUNT_SID = "cole_seu_account_sid"
TWILIO_AUTH_TOKEN = "cole_seu_auth_token"
TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"
""")
        st.markdown("### Status atual")
        st.write("Twilio instalado:", "Sim" if Client is not None else "Não")
        st.write("Credenciais configuradas:", "Sim" if twilio_configurado() else "Não")
        st.write("Número de origem:", get_secret_value("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"))
        st.caption("No Sandbox, cada funcionário precisa enviar o código join para o número da Twilio antes de receber mensagens.")

    elif aba == "Agendar Medicação":
        st.markdown("### Agendar medicação com alerta 1 hora antes")
        animais = listar_animais()
        farmacia = listar_farmacia()

        if funcionarios.empty:
            st.warning("Cadastre funcionários ativos primeiro.")
        elif animais.empty:
            st.warning("Cadastre animais primeiro.")
        else:
            col1, col2 = st.columns(2)

            with col1:
                animais["descricao"] = animais["nome"] + " - " + animais["tipo"]
                escolha_animal = st.selectbox("Animal", animais["descricao"].tolist())
                animal_nome = escolha_animal.split(" - ")[0]
                tipo_animal = escolha_animal.split(" - ")[1]

                medicamentos = ["Não informado"]
                if not farmacia.empty:
                    medicamentos += farmacia["medicamento"].dropna().tolist()

                medicamento = st.selectbox("Medicamento", medicamentos)
                dosagem = st.text_input("Dosagem / orientação")

            with col2:
                funcionarios["descricao"] = funcionarios["nome"] + " - " + funcionarios["cargo"].fillna("")
                escolha_funcionario = st.selectbox("Funcionário responsável", funcionarios["descricao"].tolist())
                funcionario_nome = escolha_funcionario.split(" - ")[0]
                funcionario = funcionarios[funcionarios["nome"] == funcionario_nome].iloc[0]

                telefone = str(funcionario["telefone"] or "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
                data_aplicacao = st.date_input("Data da medicação", format="DD/MM/YYYY")
                hora_aplicacao = st.time_input("Hora da medicação")
                obs = st.text_area("Observações")

            data_hora = datetime.combine(data_aplicacao, hora_aplicacao)

            mensagem = (
                f"Olá, {funcionario_nome}!\\n\\n"
                f"🚨 Lembrete de medicação - Rancho Recanto Verde\\n\\n"
                f"Animal: {animal_nome}\\n"
                f"Medicamento: {medicamento}\\n"
                f"Dosagem/orientação: {dosagem}\\n"
                f"Data e hora: {data_hora.strftime('%d/%m/%Y %H:%M')}\\n\\n"
                f"Favor confirmar a aplicação no sistema."
            )

            mensagem = st.text_area("Mensagem do WhatsApp", value=mensagem, height=180)

            if st.button("Salvar Agendamento"):
                c.execute("""
                    INSERT INTO medicacoes_agendadas
                    (animal, tipo_animal, medicamento, dosagem, data_hora,
                     funcionario, telefone, mensagem, status, alerta_gerado,
                     data_alerta, sid_twilio, erro_twilio, obs)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    animal_nome, tipo_animal, medicamento, dosagem,
                    data_hora.strftime("%d/%m/%Y %H:%M"),
                    funcionario_nome, telefone, mensagem,
                    "Agendada", "Não", "", "", "", obs
                ))
                conn.commit()
                st.success("Medicação agendada com sucesso!")

    elif aba == "Alertas de Medicação 1h Antes":
        st.markdown("### Medicações dentro da janela de 1 hora")
        df = pd.read_sql_query("SELECT * FROM medicacoes_agendadas WHERE status = 'Agendada'", conn)

        if df.empty:
            st.info("Nenhuma medicação agendada.")
        else:
            limite = datetime.now() + timedelta(hours=1)
            df["data_hora_dt"] = pd.to_datetime(df["data_hora"], format="%d/%m/%Y %H:%M", errors="coerce")
            alertas = df[(df["data_hora_dt"].notna()) & (df["data_hora_dt"] <= limite)].copy()

            if alertas.empty:
                st.success("Nenhuma medicação dentro da janela de 1 hora.")
            else:
                st.warning("⚠️ Existem medicações para enviar alerta.")

                for _, row in alertas.iterrows():
                    st.markdown("---")
                    col1, col2 = st.columns([2, 1])

                    with col1:
                        st.markdown(f"### 🐾 {row['animal']}")
                        st.write(f"**Medicamento:** {row['medicamento']}")
                        st.write(f"**Dosagem:** {row['dosagem']}")
                        st.write(f"**Data/Hora:** {row['data_hora']}")
                        st.write(f"**Funcionário:** {row['funcionario']}")
                        st.write(f"**Telefone:** {row['telefone']}")
                        if str(row.get("sid_twilio", "") or ""):
                            st.success(f"Twilio SID: {row.get('sid_twilio', '')}")
                        if str(row.get("erro_twilio", "") or ""):
                            st.error(f"Erro Twilio: {row.get('erro_twilio', '')}")

                    with col2:
                        numero = normalizar_whatsapp(row["telefone"])
                        link = f"https://wa.me/{numero}?text={quote(str(row['mensagem'] or ''))}"
                        st.link_button("📲 Abrir WhatsApp", link, use_container_width=True)

                        if st.button("🚀 Enviar via Twilio", key=f"twilio_{row['id']}", use_container_width=True, disabled=not twilio_configurado()):
                            ok, sid, erro = enviar_whatsapp_twilio(row["telefone"], row["mensagem"])

                            if ok:
                                c.execute("""
                                    UPDATE medicacoes_agendadas
                                    SET alerta_gerado = ?, data_alerta = ?, sid_twilio = ?, erro_twilio = ?
                                    WHERE id = ?
                                """, ("Sim", datetime.now().strftime("%d/%m/%Y %H:%M"), sid, "", str(row["id"])))

                                registrar_alerta_whatsapp(
                                    row["funcionario"], row["telefone"], "Medicação 1h antes",
                                    row["mensagem"], "Enviado via Twilio",
                                    sid_twilio=sid,
                                    obs=f"Animal: {row['animal']} | Medicamento: {row['medicamento']}"
                                )
                                st.success("Mensagem enviada pelo Twilio!")
                                st.rerun()
                            else:
                                c.execute("UPDATE medicacoes_agendadas SET erro_twilio = ? WHERE id = ?", (erro, str(row["id"])))
                                conn.commit()
                                registrar_alerta_whatsapp(
                                    row["funcionario"], row["telefone"], "Medicação 1h antes",
                                    row["mensagem"], "Erro Twilio",
                                    erro_twilio=erro,
                                    obs=f"Animal: {row['animal']} | Medicamento: {row['medicamento']}"
                                )
                                st.error(f"Erro ao enviar: {erro}")

                        if st.button("Marcar medicação como aplicada", key=f"aplicada_{row['id']}", use_container_width=True):
                            c.execute("UPDATE medicacoes_agendadas SET status = ? WHERE id = ?", ("Aplicada", str(row["id"])))
                            conn.commit()
                            st.success("Medicação marcada como aplicada.")
                            st.rerun()

            st.markdown("---")
            st.markdown("### Todos os agendamentos")
            st.dataframe(df.drop(columns=["data_hora_dt"], errors="ignore"), use_container_width=True)

    elif aba == "Enviar Alerta Manual":
        st.markdown("### Enviar alerta manual")

        if funcionarios.empty:
            st.warning("Cadastre funcionários ativos primeiro.")
        else:
            funcionarios["descricao"] = funcionarios["nome"] + " - " + funcionarios["cargo"].fillna("")
            escolha = st.selectbox("Funcionário", funcionarios["descricao"].tolist())
            funcionario_nome = escolha.split(" - ")[0]
            funcionario = funcionarios[funcionarios["nome"] == funcionario_nome].iloc[0]
            telefone = str(funcionario["telefone"] or "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

            tipo_alerta = st.selectbox("Tipo de alerta", ["Vacina / Vermifugação", "Medicamento acabando", "Parto próximo", "Recebimento em aberto", "Tratamento veterinário", "Aviso operacional", "Outro"])
            mensagem = st.text_area("Mensagem", value="Olá, favor verificar o alerta no sistema Rancho Recanto Verde.", height=160)

            numero = normalizar_whatsapp(telefone)
            st.info(f"Funcionário: {funcionario_nome} | WhatsApp: +{numero}")

            st.link_button("📲 Abrir WhatsApp com mensagem pronta", f"https://wa.me/{numero}?text={quote(mensagem)}", use_container_width=True)

            if st.button("🚀 Enviar via Twilio", use_container_width=True, disabled=not twilio_configurado()):
                ok, sid, erro = enviar_whatsapp_twilio(telefone, mensagem)
                if ok:
                    registrar_alerta_whatsapp(funcionario_nome, telefone, tipo_alerta, mensagem, "Enviado via Twilio", sid_twilio=sid)
                    st.success("Mensagem enviada pelo Twilio!")
                else:
                    registrar_alerta_whatsapp(funcionario_nome, telefone, tipo_alerta, mensagem, "Erro Twilio", erro_twilio=erro)
                    st.error(f"Erro ao enviar: {erro}")

    elif aba == "Histórico de Alertas":
        df_alertas = pd.read_sql_query("SELECT * FROM alertas_whatsapp WHERE funcionario IS NOT NULL", conn)
        df_medicacoes = pd.read_sql_query("SELECT * FROM medicacoes_agendadas WHERE animal IS NOT NULL", conn)

        st.markdown("### Histórico de alertas WhatsApp")
        if not df_alertas.empty:
            st.dataframe(df_alertas, use_container_width=True)
            st.download_button("📥 Baixar Histórico de Alertas", data=gerar_excel(df_alertas), file_name="historico_alertas_whatsapp.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.warning("Nenhum alerta registrado.")

        st.markdown("### Histórico de medicações agendadas")
        if not df_medicacoes.empty:
            st.dataframe(df_medicacoes, use_container_width=True)
        else:
            st.info("Nenhuma medicação agendada.")


# =========================================================
# RELATÓRIOS / GRÁFICOS
# =========================================================

elif op == "Relatórios / Gráficos":
    titulo_pagina("📊 Relatórios / Gráficos", "Análises gerenciais do haras")

    tratamentos = pd.read_sql_query("SELECT animal, tipo, custo_total FROM tratamentos WHERE animal IS NOT NULL", conn)
    sanitario = pd.read_sql_query("SELECT animal, tipo, custo_total FROM sanitario WHERE animal IS NOT NULL", conn)

    frames = []
    if not tratamentos.empty:
        tratamentos["origem"] = "Tratamento"
        frames.append(tratamentos)
    if not sanitario.empty:
        sanitario["origem"] = "Sanitário"
        frames.append(sanitario)

    if frames:
        df = pd.concat(frames, ignore_index=True)
        df["custo_total_num"] = pd.to_numeric(df["custo_total"], errors="coerce").fillna(0)

        resumo = df.groupby(["animal", "tipo"], as_index=False)["custo_total_num"].sum()
        resumo = resumo.rename(columns={"custo_total_num": "custo_total"})

        st.metric("Custo total geral", moeda(resumo["custo_total"].sum()))
        st.bar_chart(resumo.set_index("animal")["custo_total"])
        st.dataframe(resumo, use_container_width=True)

        st.download_button(
            "📥 Baixar Custos",
            data=gerar_excel(resumo),
            file_name="custos_por_animal.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.warning("Nenhum custo registrado ainda.")

    st.markdown("---")
    st.markdown("### 🐾 Animais por tipo")

    animais_rel = pd.read_sql_query("SELECT * FROM animais WHERE nome IS NOT NULL AND nome != ''", conn)
    if not animais_rel.empty:
        resumo_tipo = animais_rel.groupby("tipo").size().reset_index(name="quantidade")
        st.bar_chart(resumo_tipo.set_index("tipo"))
        st.dataframe(resumo_tipo, use_container_width=True)
    else:
        st.info("Nenhum animal cadastrado.")

    st.markdown("---")
    st.markdown("### 💰 Vendas e recebimentos")

    vendas_rel = pd.read_sql_query("SELECT * FROM vendas WHERE animal IS NOT NULL", conn)
    receb_rel = pd.read_sql_query("SELECT * FROM recebimentos WHERE animal IS NOT NULL", conn)

    col_v1, col_v2, col_v3 = st.columns(3)

    total_vendido_rel = 0.0
    total_recebido_rel = 0.0
    total_aberto_rel = 0.0

    if not vendas_rel.empty:
        vendas_rel["valor_num"] = pd.to_numeric(vendas_rel["valor_final"], errors="coerce").fillna(0)
        total_vendido_rel = vendas_rel["valor_num"].sum()

    if not receb_rel.empty:
        receb_rel["valor_num"] = pd.to_numeric(receb_rel["valor"], errors="coerce").fillna(0)
        total_recebido_rel = receb_rel[receb_rel["status"] == "Pago"]["valor_num"].sum()
        total_aberto_rel = receb_rel[receb_rel["status"] != "Pago"]["valor_num"].sum()

    with col_v1:
        st.metric("Total vendido", moeda(total_vendido_rel))
    with col_v2:
        st.metric("Total recebido", moeda(total_recebido_rel))
    with col_v3:
        st.metric("Total em aberto", moeda(total_aberto_rel))

    if not vendas_rel.empty:
        st.dataframe(vendas_rel, use_container_width=True)


# =========================================================
# ADMIN / USUÁRIOS
# =========================================================

elif op == "Admin / Usuários":
    titulo_pagina("⚙️ Admin / Usuários", "Cadastro de usuários e liberação de acessos")

    if st.session_state.usuario.get("perfil") != "Administrador":
        st.error("Apenas administradores podem acessar esta área.")
        st.stop()

    aba = st.radio(
        "Opção",
        ["Cadastrar Usuário", "Usuários Cadastrados", "Alterar Senha"],
        horizontal=True
    )

    if aba == "Cadastrar Usuário":
        st.markdown("### Novo usuário")

        col1, col2 = st.columns(2)

        with col1:
            nome_usuario = st.text_input("Nome de login")
            senha_usuario = st.text_input("Senha", type="password")
            perfil = st.selectbox("Perfil", list(PERFIS.keys()))

        with col2:
            ativo = st.selectbox("Ativo", ["Sim", "Não"])
            st.info("As permissões serão liberadas automaticamente conforme o perfil escolhido.")
            permissoes = PERFIS[perfil]
            st.write("Permissões:", ", ".join(permissoes))

        if st.button("Salvar Usuário"):
            if not nome_usuario or not senha_usuario:
                st.error("Informe nome e senha.")
                st.stop()

            existente = pd.read_sql_query(
                "SELECT * FROM usuarios WHERE nome = ?",
                conn,
                params=(nome_usuario,)
            )

            if not existente.empty:
                st.error("Já existe usuário com esse nome.")
                st.stop()

            c.execute("""
                INSERT INTO usuarios (nome, senha_hash, perfil, permissoes, ativo)
                VALUES (?, ?, ?, ?, ?)
            """, (
                nome_usuario,
                hash_senha(senha_usuario),
                perfil,
                "|".join(PERFIS[perfil]),
                ativo
            ))
            conn.commit()
            st.success("Usuário cadastrado com sucesso!")

    elif aba == "Usuários Cadastrados":
        df = pd.read_sql_query("SELECT id, nome, perfil, permissoes, ativo FROM usuarios", conn)

        if not df.empty:
            st.dataframe(df, use_container_width=True)

            st.markdown("### Editar usuário")
            usuario_id = st.selectbox("ID do usuário", df["id"].astype(str).tolist())
            usuario = pd.read_sql_query("SELECT * FROM usuarios WHERE id = ?", conn, params=(usuario_id,)).iloc[0]

            col1, col2 = st.columns(2)

            with col1:
                novo_perfil = st.selectbox(
                    "Perfil",
                    list(PERFIS.keys()),
                    index=list(PERFIS.keys()).index(usuario["perfil"])
                        if usuario["perfil"] in list(PERFIS.keys()) else 0
                )
                novo_ativo = st.selectbox(
                    "Ativo",
                    ["Sim", "Não"],
                    index=0 if usuario["ativo"] == "Sim" else 1
                )

            with col2:
                permissoes_atuais = str(usuario["permissoes"] or "").split("|")
                novas_permissoes = st.multiselect(
                    "Permissões",
                    TODAS_PERMISSOES,
                    default=[p for p in permissoes_atuais if p in TODAS_PERMISSOES]
                )

            if st.button("Atualizar Permissões"):
                c.execute("""
                    UPDATE usuarios
                    SET perfil = ?, permissoes = ?, ativo = ?
                    WHERE id = ?
                """, (
                    novo_perfil,
                    "|".join(novas_permissoes),
                    novo_ativo,
                    usuario_id
                ))
                conn.commit()
                st.success("Usuário atualizado com sucesso!")

        else:
            st.warning("Nenhum usuário cadastrado.")

    elif aba == "Alterar Senha":
        df = pd.read_sql_query("SELECT id, nome FROM usuarios", conn)

        if not df.empty:
            usuario_id = st.selectbox("Usuário", df["id"].astype(str).tolist())
            nova_senha = st.text_input("Nova senha", type="password")

            if st.button("Alterar Senha"):
                if not nova_senha:
                    st.error("Informe a nova senha.")
                    st.stop()

                c.execute(
                    "UPDATE usuarios SET senha_hash = ? WHERE id = ?",
                    (hash_senha(nova_senha), usuario_id)
                )
                conn.commit()
                st.success("Senha alterada com sucesso!")


# =========================================================
# GERAR PDF
# =========================================================

elif op == "Gerar PDF":
    titulo_pagina("📄 Gerar PDF", "Ficha completa do animal")

    animais = listar_animais()

    if not animais.empty:
        animal_nome = st.selectbox("Escolha o animal", animais["nome"].tolist())

        animal = pd.read_sql_query("SELECT * FROM animais WHERE nome = ?", conn, params=(animal_nome,)).iloc[0]
        pesagens = pd.read_sql_query("SELECT * FROM pesagens WHERE animal = ?", conn, params=(animal_nome,))
        sanitario = pd.read_sql_query("SELECT * FROM sanitario WHERE animal = ?", conn, params=(animal_nome,))
        tratamentos = pd.read_sql_query("SELECT * FROM tratamentos WHERE animal = ?", conn, params=(animal_nome,))
        vendas = pd.read_sql_query("SELECT * FROM vendas WHERE animal = ?", conn, params=(animal_nome,))

        if st.button("Gerar PDF"):
            buffer = BytesIO()
            pdf = canvas.Canvas(buffer, pagesize=letter)

            if os.path.exists(LOGO):
                pdf.drawImage(LOGO, 130, 690, width=350, height=100, preserveAspectRatio=True, mask="auto")

            pdf.setFont("Helvetica-Bold", 14)
            pdf.drawString(50, 650, "FICHA DO ANIMAL")

            pdf.setFont("Helvetica", 10)
            y = 625

            dados = [
                ("Nome", animal["nome"]),
                ("Tipo", animal["tipo"]),
                ("Espécie", animal["especie"]),
                ("Raça", animal["raca"]),
                ("Sexo", animal["sexo"]),
                ("Nascimento", animal["nascimento"]),
                ("Pelagem / Cor", animal["cor"]),
                ("Responsável", animal["responsavel"]),
                ("Telefone", animal["telefone"]),
                ("Local", animal["local"]),
                ("Microchip", animal["microchip"]),
                ("Status", animal["status"]),
                ("Registro ABQM", animal["registro_abqm"]),
                ("Nome oficial ABQM", animal["nome_oficial_abqm"]),
                ("Pai", animal["pai_abqm"]),
                ("Mãe", animal["mae_abqm"]),
            ]

            for titulo, valor in dados:
                pdf.drawString(50, y, f"{titulo}: {valor if valor else ''}")
                y -= 15

            secoes = [
                ("PESAGENS", pesagens, lambda row: f"{row['data_pesagem']} | Peso: {row['peso']} | Obs.: {row['obs']}"),
                ("SANITÁRIO", sanitario, lambda row: f"{row['procedimento']} | {row['produto']} | Aplic.: {row['data_aplicacao']} | Próx.: {row['proxima_dose']}"),
                ("TRATAMENTOS", tratamentos, lambda row: f"{row['data']} | {row['motivo']} | Med.: {row['medicamento']} | Custo: {moeda(row['custo_total'])}"),
                ("VENDAS", vendas, lambda row: f"{row['data_venda']} | Comprador: {row['comprador_nome']} | Valor: {moeda(row['valor_final'])} | Status: {row['status_venda']}"),
            ]

            for titulo, df_secao, formatador in secoes:
                y -= 10
                if y < 80:
                    pdf.showPage()
                    y = 750

                pdf.setFont("Helvetica-Bold", 13)
                pdf.drawString(50, y, titulo)
                y -= 20
                pdf.setFont("Helvetica", 9)

                if not df_secao.empty:
                    for _, row in df_secao.iterrows():
                        pdf.drawString(50, y, formatador(row)[:115])
                        y -= 15
                        if y < 70:
                            pdf.showPage()
                            y = 750
                            pdf.setFont("Helvetica", 9)
                else:
                    pdf.drawString(50, y, "Nenhum registro.")
                    y -= 15

            pdf.save()

            st.download_button(
                "📄 Baixar PDF da Ficha",
                data=buffer.getvalue(),
                file_name=f"ficha_{animal_nome}.pdf",
                mime="application/pdf"
            )
    else:
        st.warning("Nenhum animal cadastrado ainda.")
