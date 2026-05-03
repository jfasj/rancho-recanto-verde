
import os
import sqlite3
import hashlib
import xml.etree.ElementTree as ET
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
    "status", "obs"
]:
    add_col("alertas_whatsapp", col)

for col in [
    "animal", "tipo_animal", "medicamento", "dosagem", "data_hora",
    "funcionario", "telefone", "mensagem", "status", "alerta_gerado",
    "data_alerta", "obs"
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


def baixar_estoque(produto, quantidade):
    if produto == "Nenhum" or quantidade <= 0:
        return True, 0.0, 0.0, ""

    med_df = pd.read_sql_query(
        "SELECT * FROM farmacia WHERE medicamento = ?",
        conn,
        params=(produto,)
    )

    if med_df.empty:
        return False, 0.0, 0.0, "Produto não encontrado na farmácia."

    estoque_atual = float(med_df.iloc[0]["quantidade"] or 0)
    preco_unitario = float(med_df.iloc[0]["preco"] or 0)

    if quantidade > estoque_atual:
        return False, estoque_atual, preco_unitario, "Quantidade maior que o estoque disponível."

    nova_qtd = estoque_atual - quantidade
    c.execute(
        "UPDATE farmacia SET quantidade = ? WHERE medicamento = ?",
        (str(nova_qtd), produto)
    )

    return True, nova_qtd, preco_unitario, ""


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
    titulo_pagina("📋 Animais por Tipo", "Consulte e filtre os animais cadastrados")

    df = listar_animais()

    if not df.empty:
        col1, col2 = st.columns(2)
        with col1:
            filtro = st.selectbox("Filtrar por tipo", ["Todos"] + tipos)
        with col2:
            filtro_status = st.selectbox("Filtrar por status", ["Todos", "Ativo", "Vendido", "Óbito", "Transferido", "Outro"])

        if filtro != "Todos":
            df = df[df["tipo"] == filtro]
        if filtro_status != "Todos":
            df = df[df["status"] == filtro_status]

        st.dataframe(df, use_container_width=True)

        st.download_button(
            "📥 Baixar Excel",
            data=gerar_excel(df),
            file_name="animais_rancho_recanto_verde.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.warning("Nenhum animal cadastrado ainda.")


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

                st.markdown("### Produtos encontrados")
                st.caption("Revise os dados antes de importar. Validade normalmente não vem no XML e pode ser ajustada depois na Farmácia.")

                df_editado = st.data_editor(
                    df_produtos[[
                        "importar", "produto", "ncm", "quantidade", "unidade",
                        "valor_unitario", "valor_total", "categoria", "estoque_min", "validade"
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
                            c.execute("""
                                INSERT INTO farmacia
                                (medicamento, categoria, quantidade, estoque_min, unidade,
                                 preco, validade, fornecedor, obs)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                produto_nome,
                                categoria,
                                str(quantidade),
                                str(estoque_min),
                                unidade,
                                str(preco),
                                validade,
                                dados_nfe["fornecedor"],
                                f"Importado da NF-e {dados_nfe['numero_nfe']}"
                            ))
                            importados += 1
                        else:
                            qtd_atual = limpar_numero(existente.iloc[0]["quantidade"])
                            nova_qtd = qtd_atual + quantidade

                            c.execute("""
                                UPDATE farmacia
                                SET quantidade = ?, preco = ?, fornecedor = ?
                                WHERE medicamento = ?
                            """, (
                                str(nova_qtd),
                                str(preco),
                                dados_nfe["fornecedor"],
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
    titulo_pagina("💊 Farmácia", "Controle de estoque, custo e alerta de medicações")

    aba = st.radio(
        "Opção",
        ["Cadastrar Medicamento", "Estoque", "Alertas de Estoque"],
        horizontal=True
    )

    if aba == "Cadastrar Medicamento":
        col1, col2 = st.columns(2)

        with col1:
            medicamento = st.text_input("Medicamento / Produto")
            categoria = st.selectbox(
                "Categoria",
                ["Antibiótico", "Anti-inflamatório", "Vermífugo", "Vacina", "Suplemento", "Curativo", "Hormônio", "Reprodução", "Outro"]
            )
            quantidade = st.number_input("Quantidade em estoque", min_value=0.0, step=1.0)
            estoque_min = st.number_input("Estoque mínimo", min_value=0.0, step=1.0)
            unidade = st.selectbox("Unidade", ["ml", "dose", "comprimido", "frasco", "ampola", "sachê", "kg", "g", "unidade"])

        with col2:
            preco = st.number_input("Preço unitário", min_value=0.0, step=1.0)
            validade = st.date_input("Validade", format="DD/MM/YYYY")
            fornecedor = st.text_input("Fornecedor")
            obs = st.text_area("Observações")

        if st.button("Salvar Medicamento"):
            c.execute("""
                INSERT INTO farmacia
                (medicamento, categoria, quantidade, estoque_min, unidade, preco, validade, fornecedor, obs)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                medicamento, categoria, str(quantidade), str(estoque_min),
                unidade, str(preco), br_data(validade), fornecedor, obs
            ))
            conn.commit()
            st.success("Medicamento cadastrado com sucesso!")

    elif aba == "Estoque":
        df = listar_farmacia()

        if not df.empty:
            df["quantidade_num"] = pd.to_numeric(df["quantidade"], errors="coerce").fillna(0)
            df["preco_num"] = pd.to_numeric(df["preco"], errors="coerce").fillna(0)
            df["valor_total"] = df["quantidade_num"] * df["preco_num"]

            st.metric("Valor total em estoque", moeda(df["valor_total"].sum()))
            st.dataframe(df, use_container_width=True)

            st.download_button(
                "📥 Baixar Estoque",
                data=gerar_excel(df),
                file_name="estoque_farmacia.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("Nenhum medicamento cadastrado.")

    elif aba == "Alertas de Estoque":
        df = listar_farmacia()

        if not df.empty:
            df["quantidade_num"] = pd.to_numeric(df["quantidade"], errors="coerce").fillna(0)
            df["estoque_min_num"] = pd.to_numeric(df["estoque_min"], errors="coerce").fillna(0)

            def status_estoque(row):
                if row["quantidade_num"] <= 0:
                    return "ACABOU"
                elif row["quantidade_num"] <= row["estoque_min_num"]:
                    return "ESTOQUE BAIXO"
                return "OK"

            df["status"] = df.apply(status_estoque, axis=1)
            alertas = df[df["status"] != "OK"]

            if not alertas.empty:
                st.warning("⚠️ Existem medicamentos acabando ou zerados.")
                st.dataframe(alertas, use_container_width=True)
            else:
                st.success("Todos os medicamentos estão com estoque adequado.")

            st.dataframe(df, use_container_width=True)
        else:
            st.warning("Nenhum medicamento cadastrado.")


# =========================================================
# VETERINÁRIO / TRATAMENTOS
# =========================================================

elif op == "Veterinário / Tratamentos":
    titulo_pagina("🩺 Veterinário / Tratamentos", "Atendimentos, diagnósticos, baixa de estoque e alerta WhatsApp automático")

    aba = st.radio(
        "Opção",
        ["Registrar Tratamento", "Histórico de Tratamentos"],
        horizontal=True
    )

    animais = listar_animais()
    farmacia = listar_farmacia()
    funcionarios = pd.read_sql_query(
        "SELECT * FROM funcionarios WHERE nome IS NOT NULL AND nome != '' AND status = 'Ativo'",
        conn
    )

    if aba == "Registrar Tratamento":
        if animais.empty:
            st.warning("Cadastre um animal primeiro.")
        else:
            animais["descricao"] = animais["nome"] + " - " + animais["tipo"]
            escolha = st.selectbox("Animal", animais["descricao"].tolist())

            animal_nome = escolha.split(" - ")[0]
            animal_tipo = escolha.split(" - ")[1]

            col1, col2 = st.columns(2)

            with col1:
                data = st.date_input("Data do atendimento", format="DD/MM/YYYY")
                motivo = st.text_input("Motivo do atendimento")
                diagnostico = st.text_area("Diagnóstico")
                tratamento = st.text_area("Tratamento indicado")

            with col2:
                medicamentos = ["Nenhum"]
                if not farmacia.empty:
                    medicamentos += farmacia["medicamento"].dropna().tolist()

                medicamento = st.selectbox("Medicamento utilizado", medicamentos)

                estoque_atual = 0.0
                preco_unitario = 0.0
                unidade_padrao = ""

                if medicamento != "Nenhum":
                    med_df = pd.read_sql_query("SELECT * FROM farmacia WHERE medicamento = ?", conn, params=(medicamento,))
                    if not med_df.empty:
                        estoque_atual = float(med_df.iloc[0]["quantidade"] or 0)
                        preco_unitario = float(med_df.iloc[0]["preco"] or 0)
                        unidade_padrao = med_df.iloc[0]["unidade"] or ""
                        st.info(f"Estoque atual: {estoque_atual} {unidade_padrao} | Preço unitário: {moeda(preco_unitario)}")

                quantidade_usada = st.number_input("Quantidade usada", min_value=0.0, step=1.0)
                unidade = st.text_input("Unidade usada", value=unidade_padrao)
                dosagem = st.text_input("Dosagem / Forma de uso")
                veterinario = st.text_input("Veterinário / Responsável técnico")
                retorno = st.date_input("Retorno previsto", format="DD/MM/YYYY")

                custo_total = quantidade_usada * preco_unitario
                st.metric("Custo estimado do tratamento", moeda(custo_total))

            st.markdown("---")
            st.markdown("### 📲 Alerta WhatsApp da medicação")

            gerar_alerta = st.checkbox(
                "Gerar alerta WhatsApp para funcionário 1 hora antes da medicação",
                value=True
            )

            funcionario_nome = ""
            telefone_funcionario = ""

            col_alerta1, col_alerta2 = st.columns(2)

            with col_alerta1:
                data_medicacao = st.date_input("Data da medicação", value=data, format="DD/MM/YYYY")
                hora_medicacao = st.time_input("Hora da medicação")

            with col_alerta2:
                if funcionarios.empty:
                    st.warning("Cadastre funcionário ativo para gerar alerta WhatsApp.")
                else:
                    funcionarios["descricao"] = funcionarios["nome"] + " - " + funcionarios["cargo"].fillna("")
                    escolha_func = st.selectbox("Funcionário responsável pela aplicação", funcionarios["descricao"].tolist())
                    funcionario_nome = escolha_func.split(" - ")[0]
                    func = funcionarios[funcionarios["nome"] == funcionario_nome].iloc[0]
                    telefone_funcionario = str(func["telefone"] or "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
                    st.info(f"WhatsApp: {telefone_funcionario}")

            data_hora_medicacao = datetime.combine(data_medicacao, hora_medicacao)

            mensagem_alerta = (
                f"Olá, {funcionario_nome}!\\n\\n"
                f"🚨 Lembrete de medicação - Rancho Recanto Verde\\n\\n"
                f"Animal: {animal_nome}\\n"
                f"Medicamento: {medicamento}\\n"
                f"Dosagem/orientação: {dosagem}\\n"
                f"Data e hora: {data_hora_medicacao.strftime('%d/%m/%Y %H:%M')}\\n\\n"
                f"Favor confirmar a aplicação no sistema."
            )

            st.text_area("Mensagem que será enviada pelo WhatsApp", value=mensagem_alerta, height=160)

            obs = st.text_area("Observações gerais")

            if st.button("Salvar Tratamento e Baixar Estoque"):
                if medicamento != "Nenhum":
                    if quantidade_usada <= 0:
                        st.error("Informe a quantidade usada do medicamento.")
                        st.stop()

                    ok, nova_qtd, preco_unitario, erro = baixar_estoque(medicamento, quantidade_usada)
                    if not ok:
                        st.error(erro)
                        st.stop()

                if gerar_alerta and funcionarios.empty:
                    st.error("Para gerar alerta WhatsApp, cadastre ao menos um funcionário ativo.")
                    st.stop()

                c.execute("""
                    INSERT INTO tratamentos
                    (animal, tipo, data, motivo, diagnostico, tratamento,
                     medicamento, quantidade_usada, unidade, dosagem,
                     preco_unitario, custo_total, veterinario, retorno,
                     funcionario_responsavel, telefone_funcionario,
                     data_hora_medicacao, gerar_alerta_whatsapp, obs)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    animal_nome, animal_tipo, br_data(data), motivo, diagnostico, tratamento,
                    medicamento, str(quantidade_usada), unidade, dosagem,
                    str(preco_unitario), str(custo_total), veterinario, br_data(retorno),
                    funcionario_nome, telefone_funcionario,
                    data_hora_medicacao.strftime("%d/%m/%Y %H:%M"),
                    "Sim" if gerar_alerta else "Não",
                    obs
                ))

                # Cria automaticamente o alerta na aba Alertas WhatsApp
                if gerar_alerta and medicamento != "Nenhum":
                    c.execute("""
                        INSERT INTO medicacoes_agendadas
                        (animal, tipo_animal, medicamento, dosagem, data_hora,
                         funcionario, telefone, mensagem, status, alerta_gerado,
                         data_alerta, obs)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        animal_nome,
                        animal_tipo,
                        medicamento,
                        dosagem,
                        data_hora_medicacao.strftime("%d/%m/%Y %H:%M"),
                        funcionario_nome,
                        telefone_funcionario,
                        mensagem_alerta,
                        "Agendada",
                        "Não",
                        "",
                        f"Gerado automaticamente pelo tratamento em {br_data(data)}"
                    ))

                conn.commit()

                if gerar_alerta and medicamento != "Nenhum":
                    st.success("Tratamento salvo, estoque baixado e alerta WhatsApp agendado para 1 hora antes.")
                else:
                    st.success(f"Tratamento salvo. Custo: {moeda(custo_total)}")

    elif aba == "Histórico de Tratamentos":
        df = pd.read_sql_query("SELECT * FROM tratamentos WHERE animal IS NOT NULL", conn)

        if not df.empty:
            col1, col2 = st.columns(2)

            with col1:
                filtro = st.selectbox("Filtrar por tipo", ["Todos"] + tipos)
            with col2:
                filtro_animal = st.selectbox("Filtrar por animal", ["Todos"] + sorted(df["animal"].dropna().unique().tolist()))

            if filtro != "Todos":
                df = df[df["tipo"] == filtro]
            if filtro_animal != "Todos":
                df = df[df["animal"] == filtro_animal]

            st.dataframe(df, use_container_width=True)

            st.download_button(
                "📥 Baixar Histórico",
                data=gerar_excel(df),
                file_name="historico_tratamentos.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("Nenhum tratamento registrado.")


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
        ["Cadastrar Funcionário", "Funcionários Cadastrados"],
        horizontal=True
    )

    if aba == "Cadastrar Funcionário":
        col1, col2 = st.columns(2)

        with col1:
            nome = st.text_input("Nome completo")
            cpf = st.text_input("CPF")
            rg = st.text_input("RG")
            telefone = st.text_input("Telefone / WhatsApp")
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

            if filtro_status != "Todos":
                df = df[df["status"] == filtro_status]
            if filtro_setor != "Todos":
                df = df[df["setor"] == filtro_setor]

            if not df.empty:
                df["salario_num"] = pd.to_numeric(df["salario"], errors="coerce").fillna(0)
                st.metric("Folha mensal filtrada", moeda(df["salario_num"].sum()))

            st.dataframe(df, use_container_width=True)

            st.download_button(
                "📥 Baixar Funcionários",
                data=gerar_excel(df),
                file_name="funcionarios_rancho_recanto_verde.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("Nenhum funcionário cadastrado.")


# =========================================================
# ALERTAS WHATSAPP
# =========================================================

elif op == "Alertas WhatsApp":
    titulo_pagina("📲 Alertas WhatsApp", "Alertas para funcionários e lembretes de medicação")

    funcionarios = pd.read_sql_query(
        "SELECT * FROM funcionarios WHERE nome IS NOT NULL AND nome != '' AND status = 'Ativo'",
        conn
    )

    animais = listar_animais()
    farmacia = listar_farmacia()

    aba = st.radio(
        "Opção",
        ["Agendar Medicação", "Alertas de Medicação 1h Antes", "Enviar Alerta Manual", "Histórico de Alertas"],
        horizontal=True
    )

    # -----------------------------------------------------
    # AGENDAR MEDICAÇÃO
    # -----------------------------------------------------
    if aba == "Agendar Medicação":
        st.markdown("### Agendar medicação com alerta 1 hora antes")

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

            mensagem_padrao = (
                f"Olá, {funcionario_nome}!\\n\\n"
                f"Lembrete de medicação do Rancho Recanto Verde.\\n"
                f"Animal: {animal_nome}\\n"
                f"Medicamento: {medicamento}\\n"
                f"Dosagem/orientação: {dosagem}\\n"
                f"Data e hora: {data_hora.strftime('%d/%m/%Y %H:%M')}\\n\\n"
                f"Favor confirmar a aplicação no sistema."
            )

            mensagem = st.text_area("Mensagem do WhatsApp", value=mensagem_padrao, height=180)

            if st.button("Salvar Agendamento"):
                c.execute("""
                    INSERT INTO medicacoes_agendadas
                    (animal, tipo_animal, medicamento, dosagem, data_hora,
                     funcionario, telefone, mensagem, status, alerta_gerado,
                     data_alerta, obs)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    animal_nome,
                    tipo_animal,
                    medicamento,
                    dosagem,
                    data_hora.strftime("%d/%m/%Y %H:%M"),
                    funcionario_nome,
                    telefone,
                    mensagem,
                    "Agendada",
                    "Não",
                    "",
                    obs
                ))
                conn.commit()
                st.success("Medicação agendada com sucesso!")

    # -----------------------------------------------------
    # ALERTAS DE MEDICAÇÃO 1H ANTES
    # -----------------------------------------------------
    elif aba == "Alertas de Medicação 1h Antes":
        st.markdown("### Medicações para alertar")

        df = pd.read_sql_query(
            "SELECT * FROM medicacoes_agendadas WHERE status = 'Agendada'",
            conn
        )

        if df.empty:
            st.info("Nenhuma medicação agendada.")
        else:
            agora = datetime.now()
            limite = agora + timedelta(hours=1)

            df["data_hora_dt"] = pd.to_datetime(
                df["data_hora"],
                format="%d/%m/%Y %H:%M",
                errors="coerce"
            )

            alertas = df[
                (df["data_hora_dt"].notna()) &
                (df["data_hora_dt"] <= limite)
            ].copy()

            if alertas.empty:
                st.success("Nenhuma medicação dentro da janela de 1 hora.")
            else:
                st.warning("⚠️ Existem medicações para enviar alerta ao funcionário.")

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

                    with col2:
                        numero = str(row["telefone"] or "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
                        if numero and not numero.startswith("55"):
                            numero = "55" + numero

                        texto = quote(str(row["mensagem"] or ""))
                        link = f"https://wa.me/{numero}?text={texto}"

                        st.link_button("📲 Enviar WhatsApp", link, use_container_width=True)

                        if st.button("Marcar alerta como enviado", key=f"enviado_{row['id']}", use_container_width=True):
                            c.execute("""
                                UPDATE medicacoes_agendadas
                                SET alerta_gerado = ?, data_alerta = ?
                                WHERE id = ?
                            """, (
                                "Sim",
                                datetime.now().strftime("%d/%m/%Y %H:%M"),
                                str(row["id"])
                            ))

                            c.execute("""
                                INSERT INTO alertas_whatsapp
                                (funcionario, telefone, tipo_alerta, mensagem, data_envio, status, obs)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (
                                row["funcionario"],
                                row["telefone"],
                                "Medicação 1h antes",
                                row["mensagem"],
                                datetime.now().strftime("%d/%m/%Y %H:%M"),
                                "Gerado",
                                f"Animal: {row['animal']} | Medicamento: {row['medicamento']}"
                            ))

                            conn.commit()
                            st.success("Alerta registrado como enviado.")
                            st.rerun()

                        if st.button("Marcar medicação como aplicada", key=f"aplicada_{row['id']}", use_container_width=True):
                            c.execute("""
                                UPDATE medicacoes_agendadas
                                SET status = ?
                                WHERE id = ?
                            """, ("Aplicada", str(row["id"])))
                            conn.commit()
                            st.success("Medicação marcada como aplicada.")
                            st.rerun()

            st.markdown("---")
            st.markdown("### Todos os agendamentos")
            st.dataframe(df.drop(columns=["data_hora_dt"], errors="ignore"), use_container_width=True)

    # -----------------------------------------------------
    # ALERTA MANUAL
    # -----------------------------------------------------
    elif aba == "Enviar Alerta Manual":
        if funcionarios.empty:
            st.warning("Cadastre funcionários ativos primeiro.")
        else:
            funcionarios["descricao"] = funcionarios["nome"] + " - " + funcionarios["cargo"].fillna("")
            escolha = st.selectbox("Funcionário", funcionarios["descricao"].tolist())
            funcionario_nome = escolha.split(" - ")[0]

            funcionario = funcionarios[funcionarios["nome"] == funcionario_nome].iloc[0]
            telefone = str(funcionario["telefone"] or "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

            tipo_alerta = st.selectbox(
                "Tipo de alerta",
                [
                    "Vacina / Vermifugação",
                    "Medicamento acabando",
                    "Parto próximo",
                    "Recebimento em aberto",
                    "Tratamento veterinário",
                    "Aviso operacional",
                    "Outro"
                ]
            )

            sugestoes = {
                "Vacina / Vermifugação": "Olá, temos vacina/vermifugação próxima ou vencida no sistema. Favor verificar o Controle Sanitário.",
                "Medicamento acabando": "Olá, há medicamento com estoque baixo na Farmácia do haras. Favor verificar reposição.",
                "Parto próximo": "Olá, há previsão de parto próxima no módulo de Reprodução. Favor acompanhar a receptora.",
                "Recebimento em aberto": "Olá, existem recebimentos em aberto no financeiro. Favor verificar.",
                "Tratamento veterinário": "Olá, há tratamento veterinário/retorno previsto. Favor verificar o módulo Veterinário.",
                "Aviso operacional": "Olá, favor verificar as demandas operacionais do haras no sistema.",
                "Outro": ""
            }

            mensagem = st.text_area("Mensagem", value=sugestoes.get(tipo_alerta, ""), height=160)

            col1, col2 = st.columns(2)
            with col1:
                st.info(f"Funcionário: {funcionario_nome}")
            with col2:
                st.info(f"WhatsApp: {telefone}")

            if telefone:
                numero = telefone
                if not numero.startswith("55"):
                    numero = "55" + numero

                link = f"https://wa.me/{numero}?text={quote(mensagem)}"
                st.link_button("📲 Abrir WhatsApp com mensagem pronta", link)

            if st.button("Registrar Alerta no Histórico"):
                c.execute("""
                    INSERT INTO alertas_whatsapp
                    (funcionario, telefone, tipo_alerta, mensagem, data_envio, status, obs)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    funcionario_nome,
                    telefone,
                    tipo_alerta,
                    mensagem,
                    datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "Gerado",
                    ""
                ))
                conn.commit()
                st.success("Alerta registrado no histórico.")

    # -----------------------------------------------------
    # HISTÓRICO
    # -----------------------------------------------------
    elif aba == "Histórico de Alertas":
        df_alertas = pd.read_sql_query("SELECT * FROM alertas_whatsapp WHERE funcionario IS NOT NULL", conn)
        df_medicacoes = pd.read_sql_query("SELECT * FROM medicacoes_agendadas WHERE animal IS NOT NULL", conn)

        st.markdown("### Histórico de alertas WhatsApp")
        if not df_alertas.empty:
            st.dataframe(df_alertas, use_container_width=True)
            st.download_button(
                "📥 Baixar Histórico de Alertas",
                data=gerar_excel(df_alertas),
                file_name="historico_alertas_whatsapp.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("Nenhum alerta registrado.")

        st.markdown("### Histórico de medicações agendadas")
        if not df_medicacoes.empty:
            st.dataframe(df_medicacoes, use_container_width=True)
            st.download_button(
                "📥 Baixar Medicações Agendadas",
                data=gerar_excel(df_medicacoes),
                file_name="medicacoes_agendadas.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
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

