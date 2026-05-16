import os
import re
import hashlib
import xml.etree.ElementTree as ET
try:
    import psycopg2
    import psycopg2.extras
    from sqlalchemy import create_engine
    _PG_OK = True
except ImportError:
    _PG_OK = False

try:
    from twilio.rest import Client
except Exception:
    Client = None
from datetime import datetime, date, timedelta
from urllib.parse import quote
from io import BytesIO

import pandas as pd
import streamlit as st
try:
    from streamlit_autorefresh import st_autorefresh
    _AUTOREFRESH_OK = True
except ImportError:
    _AUTOREFRESH_OK = False
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import unicodedata


def _registrar_fonte_pdf():
    """Registra DejaVuSans (suporta acentos) se disponível, senão usa Helvetica com fallback."""
    fontes_ttf = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for caminho in fontes_ttf:
        if os.path.exists(caminho):
            try:
                if "Bold" in caminho or "Bold" in caminho:
                    pdfmetrics.registerFont(TTFont("FontePDF-Bold", caminho))
                else:
                    pdfmetrics.registerFont(TTFont("FontePDF", caminho))
            except Exception:
                pass
    return "FontePDF" if "FontePDF" in [f.fontName for f in pdfmetrics.getRegisteredFontNames()] else None


_FONTE_PDF = None


def _init_fonte_pdf():
    global _FONTE_PDF
    if _FONTE_PDF is None:
        _FONTE_PDF = _registrar_fonte_pdf()
    return _FONTE_PDF


def _fonte(bold=False):
    """Retorna nome da fonte PDF com suporte a acentos se disponível."""
    nomes = pdfmetrics.getRegisteredFontNames()
    if bold:
        return "FontePDF-Bold" if "FontePDF-Bold" in nomes else "Helvetica-Bold"
    return "FontePDF" if "FontePDF" in nomes else "Helvetica"


def _pdf_str(texto):
    """Converte texto para string segura para PDF (remove chars não suportados)."""
    if texto is None:
        return ""
    texto = str(texto)
    # Normaliza caracteres unicode compostos
    texto = unicodedata.normalize("NFC", texto)
    return texto


# =========================================================
# CONFIGURAÇÃO
# =========================================================

st.set_page_config(
    page_title="Rancho Recanto Verde",
    page_icon="https://raw.githubusercontent.com/jfasj/rancho-recanto-verde/main/logo.png",
    layout="wide",
    initial_sidebar_state="expanded"
)

LOGO = "logo.png"

def get_secret_value_early(nome, padrao=""):
    try:
        if nome in st.secrets:
            return st.secrets[nome]
    except Exception:
        pass
    return os.environ.get(nome, padrao)


@st.cache_resource
def get_connection():
    """Conecta ao Supabase via SESSION POOLER (compatível com IPv4/Streamlit Cloud)."""
    db_url = get_secret_value_early("DATABASE_URL")
    if not db_url:
        st.error("❌ DATABASE_URL não configurada nos Secrets do Streamlit.")
        st.stop()
    try:
        conn = psycopg2.connect(
            db_url,
            cursor_factory=psycopg2.extras.RealDictCursor,
            sslmode="require",
            connect_timeout=15,
        )
        conn.autocommit = False
        return conn
    except Exception as e:
        st.error(f"❌ Erro ao conectar ao banco de dados: {e}")
        st.info("Verifique a DATABASE_URL nos Secrets do Streamlit Cloud.")
        st.stop()


@st.cache_resource
def get_engine():
    """SQLAlchemy engine para uso com pd.read_sql_query."""
    db_url = get_secret_value_early("DATABASE_URL")
    # Garantir prefixo correto para SQLAlchemy
    if db_url and db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(db_url, connect_args={"sslmode": "require"})


def reconectar_se_necessario():
    """Reconecta ao banco se a conexão cair ou tiver transação com falha."""
    global conn, c
    try:
        # Testa se a conexão está OK
        conn.cursor().execute("SELECT 1")
        conn.rollback()  # Limpa qualquer transação pendente com falha
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            st.cache_resource.clear()
        except Exception:
            pass
        conn = get_connection()
        c = conn.cursor()


conn = get_connection()
c = conn.cursor()


# =========================================================
# BANCO DE DADOS
# =========================================================

# =========================================================
# MIGRAÇÃO DE BANCO — rápida: 1 query por tabela
# (substitui os ~150 add_col individuais do startup)
# =========================================================

# Definição completa de cada tabela: {tabela: [colunas]}
_SCHEMA = {
    "animais": [
        "nome", "tipo", "especie", "raca", "sexo", "nascimento", "cor",
        "responsavel", "cpf", "telefone", "local", "microchip", "status",
        "registro_abqm", "nome_oficial_abqm", "pai_abqm", "mae_abqm",
        "criador_abqm", "proprietario_abqm", "link_abqm", "obs_abqm", "obs",
        # Genealogia estendida (avós e bisavós)
        "avo_pat_abqm", "avo_pat_reg",
        "avo_mat_abqm", "avo_mat_reg",
        "bisavo_pp_abqm", "bisavo_pm_abqm",
        "bisavo_mp_abqm", "bisavo_mm_abqm",
        # Dados extras ABQM
        "pelagem_abqm", "modalidade_abqm", "reg_mae_abqm", "reg_pai_abqm",
    ],
    "farmacia": [
        "medicamento", "nome_comercial", "principio_ativo", "categoria",
        "quantidade", "estoque_min", "unidade",
        "preco", "validade", "fornecedor", "obs",
        "quantidade_compra", "unidade_compra", "volume_por_unidade",
        "unidade_controle", "estoque_convertido", "estoque_min_controle",
        "preco_por_controle",
    ],
    "sanitario": [
        "animal", "tipo", "procedimento", "produto", "data_aplicacao",
        "proxima_dose", "quantidade_usada", "unidade", "preco_unitario",
        "custo_total", "responsavel", "obs",
        "status_aplicacao", "data_confirmacao", "confirmado_por",
    ],
    "tratamentos": [
        "animal", "tipo", "data", "motivo", "diagnostico", "tratamento",
        "medicamento", "quantidade_usada", "unidade", "dosagem",
        "preco_unitario", "custo_total", "veterinario", "retorno",
        "funcionario_responsavel", "telefone_funcionario",
        "data_hora_medicacao", "gerar_alerta_whatsapp", "obs",
        "status_aplicacao", "data_confirmacao", "confirmado_por",
    ],
    "pesagens": ["animal", "tipo", "data_pesagem", "peso", "obs"],
    "doadoras": [
        "egua_doadora", "garanhao", "data_inseminacao", "protocolo",
        "dosagens", "data_prevista_lavagem", "data_lavagem",
        "resultado_lavagem", "embrioes_coletados", "status", "obs",
    ],
    "receptoras": [
        "receptora", "egua_doadora", "garanhao", "cruzamento",
        "data_transferencia", "dosagens", "protocolo", "previsao_parto",
        "confirmacao_prenhez", "status", "obs",
    ],
    "vendas": [
        "animal", "tipo", "data_venda", "valor_negociado", "desconto",
        "valor_final", "forma_pagamento", "parcelas", "status_venda",
        "comprador_nome", "comprador_cpf_cnpj", "comprador_telefone",
        "comprador_email", "comprador_endereco", "obs",
    ],
    "recebimentos": [
        "venda_id", "animal", "comprador", "parcela", "vencimento",
        "valor", "data_pagamento", "status", "obs",
    ],
    "funcionarios": [
        "nome", "cpf", "rg", "telefone", "email", "endereco", "cargo",
        "setor", "salario", "data_admissao", "status", "documentos", "obs",
    ],
    "usuarios": ["nome", "senha_hash", "perfil", "permissoes", "ativo"],
    "alertas_whatsapp": [
        "funcionario", "telefone", "tipo_alerta", "mensagem", "data_envio",
        "status", "sid_twilio", "erro_twilio", "obs",
    ],
    "medicacoes_agendadas": [
        "animal", "tipo_animal", "medicamento", "dosagem", "data_hora",
        "funcionario", "telefone", "mensagem", "status", "alerta_gerado",
        "data_alerta", "sid_twilio", "erro_twilio", "obs",
    ],
    "compras_nfe": [
        "chave_nfe", "numero_nfe", "data_emissao", "fornecedor",
        "cnpj_fornecedor", "produto", "ncm", "quantidade", "unidade",
        "valor_unitario", "valor_total", "data_importacao",
    ],
    "abqm_consultas": [
        "animal", "registro_abqm", "nome_oficial", "pai", "mae",
        "pelagem", "nascimento", "criador", "proprietario",
        "link_consulta", "observacoes", "data_cadastro",
    ],
    "fichas_medicas": [
        "animal", "tipo_animal", "data_atendimento", "motivo",
        "diagnostico", "tratamento_indicado", "veterinario",
        "retorno", "status", "custo_total", "obs",
    ],
    "ficha_medicacoes": [
        "ficha_id", "animal", "tipo_animal", "medicamento", "quantidade",
        "unidade", "dosagem", "data_hora", "funcionario", "telefone",
        "mensagem", "status", "alerta_gerado", "data_alerta",
        "preco_unitario", "custo_total", "obs",
    ],
    "agenda": [
        "titulo", "tipo", "data", "hora_inicio", "hora_fim",
        "animal", "funcionario", "descricao", "status", "cor", "obs",
    ],
    "auditoria": [
        "usuario", "perfil", "modulo", "acao", "descricao",
        "data_hora", "ip",
    ],
    "racao_estoque": [
        "produto", "categoria", "quantidade_kg", "unidade",
        "data_compra", "validade", "fornecedor", "preco_total",
        "preco_kg", "estoque_minimo", "obs",
    ],
    "racao_dieta": [
        "animal", "produto", "quantidade_kg", "turno", "ativo", "obs",
    ],
    "racao_fornecimento": [
        "animal", "produto", "quantidade_kg", "turno", "data",
        "responsavel", "obs",
    ],
}


@st.cache_resource
def _migrar_banco(_conn):
    """
    Executa a migração do banco UMA única vez por sessão do servidor.
    Usa 1 query por tabela (information_schema) ao invés de 1 por coluna.
    Reduz de ~150 round-trips para ~17.
    """
    cur = _conn.cursor()

    # Busca todas as colunas existentes de uma vez só
    tabelas_list = list(_SCHEMA.keys())
    cur.execute("""
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_name = ANY(%s)
    """, (tabelas_list,))
    existentes = set((r["table_name"], r["column_name"]) for r in cur.fetchall())

    for tabela, colunas in _SCHEMA.items():
        # Cria a tabela se não existir
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {tabela} (
                id SERIAL PRIMARY KEY
            )
        """)
        # Adiciona só as colunas que faltam
        for coluna in colunas:
            if (tabela, coluna) not in existentes:
                cur.execute(f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS {coluna} TEXT")

    _conn.commit()
    cur.close()
    return True


# Compatibilidade: add_col ainda usada em poucos pontos do código
def add_col(tabela, coluna, tipo="TEXT"):
    c.execute(f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS {coluna} {tipo}")


_migrar_banco(conn)


# =========================================================
# USUÁRIOS / SEGURANÇA
# =========================================================

TODAS_PERMISSOES = [
    "Dashboard",
    "Agenda",
    "Cadastrar Animal",
    "Animais por Tipo",
    "Pesagem / Evolução",
    "Controle Sanitário",
    "Farmácia",
    "Ração",
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
        "Agenda",
        "Animais por Tipo",
        "Controle Sanitário",
        "Veterinário / Tratamentos",
        "Reprodução / Embriões",
        "Alertas WhatsApp",
        "Gerar PDF",
    ],
    "Financeiro": [
        "Dashboard",
        "Agenda",
        "Vendas de Animais",
        "Importar NF-e / XML",
        "Consulta ABQM",
        "Relatórios / Gráficos",
        "Alertas WhatsApp",
        "Gerar PDF",
    ],
    "Operacional": [
        "Dashboard",
        "Agenda",
        "Cadastrar Animal",
        "Animais por Tipo",
        "Pesagem / Evolução",
        "Controle Sanitário",
        "Ração",
        "Importar NF-e / XML",
        "Consulta ABQM",
        "Funcionários",
        "Alertas WhatsApp",
    ],
}


def hash_senha(senha):
    return hashlib.sha256(str(senha).encode("utf-8")).hexdigest()


def registrar_auditoria(modulo, acao, descricao=""):
    """Registra toda ação importante do usuário logado."""
    try:
        usuario_atual = st.session_state.get("usuario", {})
        nome_u = usuario_atual.get("nome", "sistema")
        perfil_u = usuario_atual.get("perfil", "")
        c.execute("""
            INSERT INTO auditoria (usuario, perfil, modulo, acao, descricao, data_hora)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            nome_u, perfil_u, modulo, acao,
            str(descricao)[:500],
            datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        ))
        conn.commit()
    except Exception:
        pass  # Nunca deixa auditoria quebrar o fluxo principal


    """Versão antecipada de get_secret_value para uso no boot."""
    try:
        if nome in st.secrets:
            return st.secrets[nome]
    except Exception:
        pass
    import os as _os
    return _os.environ.get(nome, padrao)


def criar_admin_padrao():
    usuarios = pd.read_sql_query("SELECT * FROM usuarios WHERE nome IS NOT NULL AND nome != ''", get_engine())
    if usuarios.empty:
        c.execute("""
            INSERT INTO usuarios (nome, senha_hash, perfil, permissoes, ativo)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            "admin",
            hash_senha(_get_secret_early("ADMIN_SENHA_INICIAL", "1234")),
            "Administrador",
            "|".join(TODAS_PERMISSOES),
            "Sim"
        ))
        conn.commit()



def atualizar_admin_permissoes():
    try:
        # Garante que não há transação com falha pendente
        conn.rollback()
        c.execute("""
            UPDATE usuarios
            SET permissoes = %s, perfil = %s, ativo = %s
            WHERE nome = %s
        """, (
            "|".join(TODAS_PERMISSOES),
            "Administrador",
            "Sim",
            "admin"
        ))
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass


@st.cache_data(ttl=300)
def carregar_usuario(nome):
    df = pd.read_sql_query(
        "SELECT * FROM usuarios WHERE nome = %s AND ativo = 'Sim'",
        get_engine(),
        params=(nome,)
    )
    if df.empty:
        return None
    return df.iloc[0].to_dict()


def usuario_tem_permissao(pagina):
    if "usuario" not in st.session_state:
        return False
    permissoes = str(st.session_state.usuario.get("permissoes", ""))
    if permissoes in ("todas", "all", "Todas", "TODAS"):
        return True
    perfil = st.session_state.usuario.get("perfil", "")
    if perfil == "Administrador":
        return True
    return pagina in permissoes.split("|")


criar_admin_padrao()
if "admin_perms_atualizadas" not in st.session_state:
    reconectar_se_necessario()
    atualizar_admin_permissoes()
    st.session_state.admin_perms_atualizadas = True


# =========================================================
# VISUAL PREMIUM
# =========================================================

st.markdown("""
<style>
/* ============================================================
   RANCHO RECANTO VERDE — Design System v4 (2026)
   Layout claro inspirado na ABQM + identidade do haras
   Sidebar: verde escuro  |  Corpo: creme/areia  |  Acento: dourado
   ============================================================ */

@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;700&family=DM+Sans:wght@400;500&display=swap&subset=latin');

:root {
    /* Cores base — tema verde escuro + creme */
    --bg:        #1a3a2a;
    --surface:   #1e4230;
    --surface2:  #17331f;
    --surface3:  #142e1c;

    /* Sidebar verde mais escuro */
    --sidebar:   #142e1c;
    --sidebar2:  #0f2218;
    --sidebar3:  #0a1812;

    /* Dourado — identidade do haras */
    --gold:      #c9a84c;
    --gold-l:    #e8ca7a;
    --gold-d:    #f0d070;
    --gold-bg:   rgba(201,168,76,0.12);
    --gold-line: rgba(201,168,76,0.3);

    /* Verde haras */
    --green-brand: #4ab87a;
    --green-light: rgba(74,184,122,0.12);
    --green-line:  rgba(74,184,122,0.25);

    /* Semânticas */
    --red:    #e05a5a;
    --green:  #4ab87a;
    --yellow: #e8b84b;
    --blue:   #4a8fcf;

    /* Texto — claro sobre fundo escuro */
    --text:   #f0ece3;
    --muted:  #9ab8a8;
    --hint:   #5a7a6a;
    --line:   rgba(255,255,255,0.08);
}

/* ── Fontes base ── */
* { font-family: 'DM Sans', sans-serif !important; }

/* ── Fundo global — creme claro ── */
.stApp {
    background: var(--bg) !important;
    color: var(--text) !important;
    color-scheme: dark;
}
.main .block-container {
    padding-top: 1.5rem !important;
}

/* ── Esconde elementos do Streamlit que não queremos ── */
/* Nome do arquivo no topo da sidebar */
[data-testid="stSidebarHeader"] { display: none !important; }
[data-testid="stSidebarNavItems"] { display: none !important; }
/* Toolbar superior (deploy, share icons) */
[data-testid="stToolbar"] { display: none !important; }
/* Decoração superior */
[data-testid="stDecoration"] { display: none !important; }
/* App top menu */
#MainMenu { display: none !important; }
/* Status widget */
[data-testid="stStatusWidget"] { display: none !important; }

/* ── Sidebar — verde escuro como ABQM ── */
[data-testid="stSidebar"] {
    background: var(--sidebar) !important;
    border-right: none !important;
}
[data-testid="stSidebar"] * { color: rgba(255,255,255,0.75) !important; }

/* Itens do menu lateral */
[data-testid="stSidebar"] [role="radiogroup"] label {
    background: transparent !important;
    border: none !important;
    border-radius: 8px;
    padding: 9px 14px !important;
    margin: 2px 6px !important;
    transition: all .15s;
    cursor: pointer;
    width: 100% !important;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {
    background: rgba(255,255,255,0.08) !important;
}
/* Texto dos itens */
[data-testid="stSidebar"] [role="radiogroup"] label p,
[data-testid="stSidebar"] [role="radiogroup"] label span,
[data-testid="stSidebar"] [role="radiogroup"] label div {
    color: rgba(255,255,255,0.78) !important;
    font-size: 0.88rem !important;
    font-weight: 400 !important;
    visibility: visible !important;
    opacity: 1 !important;
    display: inline !important;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover p,
[data-testid="stSidebar"] [role="radiogroup"] label:hover span {
    color: #ffffff !important;
}
/* Item ativo */
[data-testid="stSidebar"] [role="radiogroup"] [aria-checked="true"] label {
    background: rgba(201,168,76,0.15) !important;
    border-left: 3px solid var(--gold) !important;
    border-radius: 0 8px 8px 0 !important;
    margin-left: 0 !important;
    padding-left: 17px !important;
}
[data-testid="stSidebar"] [role="radiogroup"] [aria-checked="true"] label p,
[data-testid="stSidebar"] [role="radiogroup"] [aria-checked="true"] label span {
    color: var(--gold) !important;
    font-weight: 500 !important;
}
/* Esconde APENAS o círculo do radio, não o texto */
[data-testid="stSidebar"] [role="radiogroup"] [data-testid="stWidgetLabel"] { display: none !important; }
[data-testid="stSidebar"] [role="radiogroup"] svg { display: none !important; }
[data-testid="stSidebar"] [role="radiogroup"] input[type="radio"] { display: none !important; }


/* ── Tipografia ── */
h1, h2, h3 {
    font-family: 'Playfair Display', serif !important;
    color: var(--text) !important;
    font-weight: 500 !important;
}
h1 { font-size: 1.5rem !important; }
h2 { font-size: 1.2rem !important; }
h3 { font-size: 1rem !important; }
label { color: var(--muted) !important; font-size: 0.85rem !important; }
p, span { color: var(--text); }
hr { border: none; border-top: 1px solid var(--line); }

/* ── Métricas ── */
div[data-testid="stMetric"] {
    background: var(--surface);
    border: 0.5px solid var(--line);
    border-radius: 12px;
    padding: 16px 20px;
    border-top: 3px solid var(--gold);
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}
div[data-testid="stMetricLabel"] {
    color: var(--muted) !important;
    font-size: 0.72rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
}
div[data-testid="stMetricValue"] {
    color: var(--text) !important;
    font-family: 'Playfair Display', serif !important;
    font-size: 1.8rem !important;
    font-weight: 500 !important;
}
div[data-testid="stMetricDelta"] { font-size: 0.78rem !important; }

/* ── Botões ── */
.stButton button,
.stDownloadButton button {
    background: var(--sidebar);
    color: var(--gold) !important;
    border-radius: 8px;
    font-weight: 500;
    border: none;
    padding: 0.55rem 1.2rem;
    font-size: 0.88rem;
    transition: all .18s;
}
.stButton button:hover,
.stDownloadButton button:hover {
    background: var(--sidebar2);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(26,58,42,0.2);
}

/* Botões de ação em colunas (módulos do dashboard) */
div[data-testid="column"] .stButton button {
    min-height: 120px;
    font-size: 0.95rem;
    border-radius: 12px;
    border: 0.5px solid rgba(255,255,255,0.12) !important;
    background: var(--surface) !important;
    color: var(--text) !important;
    font-weight: 500 !important;
    box-shadow: none;
    white-space: pre-wrap !important;
    line-height: 1.6 !important;
    padding: 16px 12px !important;
}
div[data-testid="column"] .stButton button:hover {
    background: var(--sidebar) !important;
    color: var(--gold) !important;
    border-color: var(--sidebar) !important;
    box-shadow: 0 6px 16px rgba(26,58,42,0.18) !important;
    transform: translateY(-3px);
}

/* ── Inputs ── */
input, textarea {
    background-color: var(--surface2) !important;
    color: var(--text) !important;
    border: 0.5px solid rgba(255,255,255,0.12) !important;
    border-radius: 8px !important;
    font-size: 0.9rem !important;
}
input:focus, textarea:focus {
    border-color: var(--green-brand) !important;
    box-shadow: 0 0 0 3px rgba(26,122,74,0.1) !important;
    outline: none !important;
}
div[data-baseweb="select"] > div {
    background-color: var(--surface2) !important;
    border-radius: 8px !important;
    border: 0.5px solid rgba(255,255,255,0.12) !important;
    color: var(--text) !important;
}
div[data-baseweb="select"] > div:focus-within {
    border-color: var(--green-brand) !important;
    box-shadow: 0 0 0 3px rgba(26,122,74,0.1) !important;
}

/* ── Selectbox dropdown ── */
[data-baseweb="popover"] {
    background: var(--surface) !important;
}

/* ── Radio buttons ── */
div[role="radiogroup"] label {
    background: var(--surface) !important;
    border: 0.5px solid rgba(255,255,255,0.12) !important;
    border-radius: 8px !important;
    padding: 8px 14px !important;
    color: var(--text) !important;
    transition: all .15s;
    font-size: 0.88rem !important;
}
div[role="radiogroup"] label:hover {
    border-color: var(--gold) !important;
    background: var(--gold-bg) !important;
}

/* ── DataFrames ── */
[data-testid="stDataFrame"] {
    border-radius: 10px;
    overflow: hidden;
    border: 0.5px solid var(--line);
    background: var(--surface);
    color: var(--text);
}

/* ── Cards ── */
.card {
    background: var(--surface);
    border: 0.5px solid var(--line);
    border-top: 3px solid var(--gold);
    border-radius: 10px;
    padding: 18px;
    transition: box-shadow .2s;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}
.card:hover {
    box-shadow: 0 4px 16px rgba(0,0,0,0.08);
}
.card-title {
    font-size: 0.7rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.card-value {
    font-family: 'Playfair Display', serif !important;
    font-size: 1.8rem;
    font-weight: 500;
    color: var(--text);
    line-height: 1;
    margin-top: 4px;
}
.card-sub { font-size: 0.78rem; color: var(--muted); margin-top: 4px; }
.card-value.gold  { color: var(--gold-d); }
.card-value.green { color: var(--green-brand); }
.card-value.red   { color: var(--red); }

/* ── Grid de módulos (dashboard) ── */
.app-grid-card {
    background: var(--surface);
    border: 0.5px solid rgba(255,255,255,0.1);
    border-radius: 12px;
    padding: 20px 14px;
    min-height: 120px;
    text-align: center;
    margin-bottom: 12px;
    cursor: pointer;
    transition: all .2s;
}
.app-grid-card:hover {
    border-color: var(--gold);
    background: var(--surface3);
    transform: translateY(-3px);
    box-shadow: 0 8px 20px rgba(26,58,42,0.15);
}
.app-grid-card:hover .app-grid-title { color: var(--gold); }
.app-grid-card:hover .app-grid-subtitle { color: rgba(255,255,255,0.6); }
.app-grid-icon { font-size: 2rem; margin-bottom: 8px; }
.app-grid-title { font-size: 0.92rem; font-weight: 500; color: var(--text); transition: color .2s; }
.app-grid-subtitle { font-size: 0.76rem; color: var(--muted); margin-top: 3px; transition: color .2s; }

/* ── Badges ── */
.badge { display: inline-block; font-size: 0.68rem; font-weight: 500; padding: 2px 9px; border-radius: 999px; letter-spacing: 0.03em; }
.badge-ok     { background: #e1f5ee; color: #0f6e56; }
.badge-warn   { background: #faeeda; color: #854f0b; }
.badge-danger { background: #fce8e8; color: #a32d2d; }
.badge-info   { background: #e6f1fb; color: #185fa5; }
.badge-gold   { background: var(--gold-bg); color: var(--gold-d); }

/* ── Topbar / Breadcrumb ── */
.topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: var(--surface);
    border: 0.5px solid var(--line);
    border-radius: 10px;
    padding: 12px 16px;
    margin-bottom: 16px;
}
.topbar-title { font-family: 'Playfair Display', serif; font-weight: 500; color: var(--text); font-size: 1rem; }
.topbar-menu { display: flex; gap: 8px; flex-wrap: wrap; }

/* ── Section titles ── */
.section-title {
    font-family: 'Playfair Display', serif !important;
    font-size: 1.3rem; font-weight: 500;
    color: var(--text); margin: 10px 0 2px;
}
.section-subtitle { color: var(--muted); margin-bottom: 16px; font-size: 0.85rem; }

/* ── Dashboard header ── */
.quick-title { font-family: 'Playfair Display', serif !important; font-size: 1.4rem; font-weight: 500; color: var(--text); }
.quick-subtitle { color: var(--muted); font-size: 0.85rem; margin-bottom: 16px; }

/* ── Alert card ── */
.alert-card { background: var(--surface); border: 0.5px solid var(--line); border-radius: 10px; padding: 16px; }

/* ── Icon box ── */
.icon-box {
    width: 44px; height: 44px; border-radius: 10px;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 1.4rem; margin-right: 10px;
    background: var(--green-light); border: 0.5px solid var(--green-line);
    flex-shrink: 0;
}

/* ── Divisor ── */
.gold-divider { height: 2px; background: linear-gradient(90deg, var(--gold), transparent); border: none; margin: 16px 0; border-radius: 99px; }

/* ── Tag de perfil ── */
.perfil-tag {
    display: inline-block;
    background: var(--gold-bg); border: 1px solid var(--gold-line);
    border-radius: 999px; padding: 2px 10px;
    font-size: 0.68rem; color: var(--gold-d); font-weight: 500; margin-top: 4px;
}

/* ── Info row ── */
.info-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 0.5px solid var(--line); font-size: 0.88rem; }
.info-row:last-child { border-bottom: none; }
.info-label { color: var(--muted); font-weight: 300; }
.info-value { color: var(--text); font-weight: 500; }

/* ── Pill ── */
.pill { border: 0.5px solid var(--green-line); border-radius: 999px; padding: 4px 12px; background: var(--green-light); color: var(--green-brand); font-weight: 500; font-size: 0.82rem; }

/* ── Accents ── */
.accent-green { color: var(--green-brand) !important; }
.accent-gold  { color: var(--gold-d) !important; }

/* ── Footer ── */
.footer { text-align: center; color: var(--hint); padding: 16px 0 4px; font-size: 0.8rem; border-top: 0.5px solid var(--line); margin-top: 24px; }

/* ── Streamlit alerts ── */
div[data-testid="stAlert"] { border-radius: 8px !important; border-width: 0.5px !important; }

/* ── Expander ── */
details { background: var(--surface); border-radius: 8px; border: 0.5px solid rgba(255,255,255,0.1) !important; }
details summary { color: var(--text) !important; font-weight: 500 !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--muted); border-radius: 99px; }
::-webkit-scrollbar-thumb:hover { background: var(--sidebar); }

/* ============================================================
   RESPONSIVO MOBILE
   ============================================================ */
@media (max-width: 768px) {
    [data-testid="stSidebar"] { min-width: 0 !important; width: 0 !important; }
    [data-testid="stSidebar"][aria-expanded="true"] {
        width: 82vw !important; min-width: 240px !important;
        position: fixed !important; z-index: 9999 !important;
        height: 100vh !important; top: 0 !important; left: 0 !important;
        box-shadow: 4px 0 24px rgba(0,0,0,0.3) !important;
    }
    .main .block-container { padding: 0.5rem 0.6rem 5rem !important; max-width: 100% !important; }
    div[data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; min-width: 100% !important; }
    .card { padding: 12px !important; }
    .topbar { flex-direction: column !important; gap: 8px !important; }
    .topbar-menu { display: none !important; }
    .app-grid-card { padding: 12px 8px !important; min-height: 100px !important; }
    .app-grid-icon { font-size: 1.6rem !important; }
    .app-grid-title { font-size: 0.85rem !important; }
    .section-title { font-size: 1.1rem !important; }
    .stButton button, .stDownloadButton button { min-height: 46px !important; font-size: 0.92rem !important; }
    div[data-testid="stMetric"] { padding: 12px !important; }
    div[role="radiogroup"] { flex-direction: column !important; }
    div[role="radiogroup"] label { width: 100% !important; min-height: 44px !important; }
    .stTextInput input { font-size: 16px !important; }
    .card-value { font-size: 1.5rem !important; }
    [data-testid="stDataFrame"] { overflow-x: auto !important; max-width: 100vw !important; }
}

@media (max-width: 400px) {
    .main .block-container { padding: 0.3rem 0.4rem 5rem !important; }
    .section-title { font-size: 1rem !important; }
    .app-grid-card { padding: 10px 6px !important; }
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


@st.cache_data(ttl=120)
def listar_animais(somente_ativos=False):
    df = pd.read_sql_query("SELECT * FROM animais WHERE nome IS NOT NULL AND nome != ''", get_engine())
    if somente_ativos and not df.empty and "status" in df.columns:
        df = df[df["status"].fillna("").str.upper() != "VENDIDO"]
    return df


@st.cache_data(ttl=120)
def listar_farmacia():
    return pd.read_sql_query("SELECT * FROM farmacia WHERE medicamento IS NOT NULL AND medicamento != ''", get_engine())


@st.cache_data(ttl=120)
def _carregar_dashboard():
    """Carrega todos os dados do dashboard em paralelo — cacheado 60s."""
    engine = get_engine()
    animais     = pd.read_sql_query("SELECT * FROM animais WHERE nome IS NOT NULL AND nome != ''", engine)
    farmacia    = pd.read_sql_query("SELECT * FROM farmacia WHERE medicamento IS NOT NULL AND medicamento != ''", engine)
    sanitario   = pd.read_sql_query("SELECT * FROM sanitario WHERE animal IS NOT NULL", engine)
    tratamentos = pd.read_sql_query("SELECT * FROM tratamentos WHERE animal IS NOT NULL", engine)
    vendas      = pd.read_sql_query("SELECT * FROM vendas WHERE animal IS NOT NULL", engine)
    recebimentos= pd.read_sql_query("SELECT * FROM recebimentos WHERE animal IS NOT NULL", engine)
    receptoras  = pd.read_sql_query("SELECT * FROM receptoras WHERE receptora IS NOT NULL", engine)
    return animais, farmacia, sanitario, tratamentos, vendas, recebimentos, receptoras


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
        "SELECT * FROM farmacia WHERE medicamento = %s", get_engine(),
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
            SET estoque_convertido = %s
            WHERE medicamento = %s
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
        SET quantidade = %s
        WHERE medicamento = %s
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

    st.markdown("""
<style>
.stApp, .stApp > div, .main, .main > div, .block-container {
    background: #1a3a2a !important;
    padding: 0 !important;
    margin: 0 !important;
    max-width: 100% !important;
}
[data-testid="stSidebar"], header, #MainMenu, footer { display: none !important; }
html, body { background: #1a3a2a !important; overflow-y: hidden !important; }
/* Esconde scrollbar mas mantém scroll funcional se necessário */
html::-webkit-scrollbar { display: none !important; }
html { -ms-overflow-style: none !important; scrollbar-width: none !important; }

/* Centra o form no meio da tela */
div[data-testid="stForm"] {
    background: rgba(255,255,255,0.07) !important;
    border: 1px solid rgba(201,168,76,0.25) !important;
    border-radius: 16px !important;
    padding: 8px 20px 16px !important;
}
div[data-testid="stForm"] label { color: rgba(255,255,255,0.7) !important; }
div[data-testid="stForm"] input {
    background: rgba(255,255,255,0.06) !important;
    color: #ffffff !important;
    border-color: rgba(255,255,255,0.15) !important;
}
div[data-testid="stForm"] button[kind="primaryFormSubmit"],
div[data-testid="stForm"] button {
    background: #c9a84c !important;
    color: #1a3a2a !important;
    font-weight: 600 !important;
    border: none !important;
    margin-top: 6px !important;
}
div[data-testid="stForm"] button:hover {
    background: #e8ca7a !important;
}
</style>
""", unsafe_allow_html=True)

    # Espaço topo calculado para centralizar (logo ~200px + subtitulo + form ~220px = ~500px total, centralizando com padding)
    _logo_html = f"<img src='https://raw.githubusercontent.com/jfasj/rancho-recanto-verde/main/logo.png' style='width:100%;max-width:380px;display:block;margin:0 auto 6px' />" if not os.path.exists(LOGO) else ""

    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.markdown("<div style='margin-top:-55px'></div>", unsafe_allow_html=True)

        if os.path.exists(LOGO):
            st.image(LOGO, width="stretch")
        else:
            st.markdown(_logo_html, unsafe_allow_html=True)

        st.markdown("<div style='margin-top:-255px'></div>", unsafe_allow_html=True)

        st.markdown("""
<div style='font-size:0.92rem;font-weight:500;color:#ffffff;margin:0 0 4px;
padding-left:4px'>🔒 Acesso ao Sistema</div>
""", unsafe_allow_html=True)

        # Formulário — Enter funciona nativamente
        with st.form("form_login", clear_on_submit=False):
            nome_login  = st.text_input("Usuário", placeholder="Digite seu usuário")
            senha_login = st.text_input("Senha", type="password", placeholder="Digite sua senha")
            entrar      = st.form_submit_button("Entrar", use_container_width=True)

        if entrar:
            usuario = carregar_usuario(nome_login)
            if usuario and usuario["senha_hash"] == hash_senha(senha_login):
                st.session_state.logado       = True
                st.session_state.usuario      = usuario
                st.session_state.pagina_atual = "Dashboard"
                registrar_auditoria("Login", "Acesso", f"Login realizado com sucesso")
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")

    st.stop()


# ── Autorefresh: placeholder — chamada real fica após definição das funções ──
if _AUTOREFRESH_OK:
    _refresh_count = st_autorefresh(interval=10 * 60 * 1000, key="alert_autorefresh")
else:
    st.sidebar.caption("⚠️ Instale streamlit-autorefresh para alertas automáticos.")
    _refresh_count = 0


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
    """Limpa o numero e adiciona DDI 55 se necessario. Retorna so digitos."""
    numero = str(numero or "")
    numero = numero.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if numero and not numero.startswith("55"):
        numero = "55" + numero
    return numero


def _variantes_numero(numero):
    """
    Gera as duas variantes de um numero BR: com e sem o 9 extra.
    Ex: 558195640909  -> [558195640909, 5581995640909]
        5581995640909 -> [5581995640909, 558195640909]
    Assim o envio tenta automaticamente os dois formatos.
    """
    numero = normalizar_whatsapp(numero)
    if not numero:
        return []
    variantes = [numero]
    if len(numero) == 12 and numero.startswith("55"):
        com_nove = numero[:4] + "9" + numero[4:]
        variantes.append(com_nove)
    elif len(numero) == 13 and numero.startswith("55"):
        sem_nove = numero[:4] + numero[5:]
        variantes.append(sem_nove)
    return variantes


def enviar_whatsapp_twilio(numero, mensagem):
    if Client is None:
        return False, "", "Biblioteca twilio nao instalada. Inclua twilio no requirements.txt."

    sid = get_secret_value("TWILIO_ACCOUNT_SID")
    token = get_secret_value("TWILIO_AUTH_TOKEN")
    from_number = get_secret_value("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

    if not sid or not token:
        return False, "", "Credenciais Twilio nao configuradas."

    variantes = _variantes_numero(numero)
    if not variantes:
        return False, "", "Telefone do funcionario nao informado."

    client = Client(sid, token)
    ultimo_erro = ""

    for num in variantes:
        try:
            msg = client.messages.create(
                body=str(mensagem),
                from_=from_number,
                to=f"whatsapp:+{num}"
            )
            return True, msg.sid, ""
        except Exception as e:
            ultimo_erro = str(e)
            continue

    return False, "", ultimo_erro


def registrar_alerta_whatsapp(funcionario, telefone, tipo_alerta, mensagem, status, sid_twilio="", erro_twilio="", obs=""):
    c.execute("""
        INSERT INTO alertas_whatsapp
        (funcionario, telefone, tipo_alerta, mensagem, data_envio, status, sid_twilio, erro_twilio, obs)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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


def verificar_e_disparar_alertas_auto():
    """
    Verifica medicações agendadas dentro da janela de 1 hora e envia
    via Twilio automaticamente se ainda não foram enviadas.
    Deve ser chamada a cada ciclo do autorefresh.
    """
    if not twilio_configurado():
        return 0

    try:
        df = pd.read_sql_query(
            "SELECT * FROM medicacoes_agendadas WHERE status = 'Agendada' AND alerta_gerado = 'Não'",
            conn
        )
    except Exception:
        return 0

    if df.empty:
        return 0

    agora = datetime.now()
    limite = agora + timedelta(hours=1)
    df["data_hora_dt"] = pd.to_datetime(df["data_hora"], format="%d/%m/%Y %H:%M", errors="coerce")
    pendentes = df[
        (df["data_hora_dt"].notna()) &
        (df["data_hora_dt"] >= agora) &
        (df["data_hora_dt"] <= limite)
    ]

    enviados = 0
    for _, row in pendentes.iterrows():
        ok, sid, erro = enviar_whatsapp_twilio(row["telefone"], row["mensagem"])
        if ok:
            c.execute("""
                UPDATE medicacoes_agendadas
                SET alerta_gerado = %s, data_alerta = %s, sid_twilio = %s, erro_twilio = %s
                WHERE id = %s
            """, ("Sim", agora.strftime("%d/%m/%Y %H:%M"), sid, "", str(row["id"])))
            registrar_alerta_whatsapp(
                row["funcionario"], row["telefone"], "Medicação 1h antes (auto)",
                row["mensagem"], "Enviado via Twilio (automático)",
                sid_twilio=sid,
                obs=f"Animal: {row['animal']} | Medicamento: {row['medicamento']}"
            )
            enviados += 1
        else:
            c.execute(
                "UPDATE medicacoes_agendadas SET erro_twilio = %s WHERE id = %s",
                (erro, str(row["id"]))
            )
        conn.commit()

    return enviados


# ── Autorefresh: dispara alertas após função estar definida ──
if _AUTOREFRESH_OK and _refresh_count > 0:
    _enviados_auto = verificar_e_disparar_alertas_auto()
    if _enviados_auto > 0:
        st.toast(f"✅ {_enviados_auto} alerta(s) WhatsApp enviado(s) automaticamente!", icon="📲")


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
    df = pd.read_sql_query("SELECT * FROM farmacia", get_engine())
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
            SET volume_por_unidade = %s,
                unidade_controle = %s,
                estoque_convertido = %s,
                quantidade_compra = %s,
                preco_por_controle = %s
            WHERE id = %s
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
        df = pd.read_sql_query("SELECT * FROM farmacia", get_engine())
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
                SET quantidade_compra = %s,
                    unidade_compra = %s,
                    volume_por_unidade = %s,
                    unidade_controle = %s,
                    estoque_convertido = %s,
                    estoque_min_controle = %s,
                    preco_por_controle = %s
                WHERE id = %s
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
# Tabelas fichas_medicas e ficha_medicacoes já criadas pelo _migrar_banco acima.



# =========================================================
# SIDEBAR / MENU
# =========================================================

with st.sidebar:
    if os.path.exists(LOGO):
        st.image(LOGO, width="stretch")
    else:
        st.markdown("""
<div style='padding:4px 0 16px;border-bottom:1px solid rgba(255,255,255,0.1);margin-bottom:12px'>
  <div style='font-family:"Playfair Display",serif;font-size:1rem;color:#c9a84c;font-weight:500;line-height:1.25'>Rancho Recanto Verde</div>
  <div style='font-size:0.68rem;color:rgba(255,255,255,0.4);letter-spacing:0.12em;text-transform:uppercase;margin-top:3px;font-weight:400'>Sistema de Gestão</div>
</div>
""", unsafe_allow_html=True)

    # Info do usuário logado
    if "usuario" in st.session_state and st.session_state.usuario:
        _nome_u = st.session_state.usuario.get("nome", "")
        _perfil_u = st.session_state.usuario.get("perfil", "")
        _iniciais = "".join([p[0].upper() for p in _nome_u.split()[:2]]) if _nome_u else "?"
        st.markdown(f"""
<div style='display:flex;align-items:center;gap:10px;padding:8px 0 14px;border-bottom:1px solid rgba(255,255,255,0.1);margin-bottom:10px'>
  <div style='width:36px;height:36px;border-radius:50%;background:rgba(201,168,76,0.2);border:1px solid rgba(201,168,76,0.4);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:500;color:#c9a84c;flex-shrink:0'>{_iniciais}</div>
  <div>
    <div style='font-size:0.85rem;font-weight:500;color:#ffffff'>{_nome_u}</div>
    <div style='display:inline-block;background:rgba(201,168,76,0.15);border:1px solid rgba(201,168,76,0.3);border-radius:999px;padding:1px 9px;font-size:0.65rem;color:#c9a84c;font-weight:500;margin-top:2px;letter-spacing:0.04em'>{_perfil_u}</div>
  </div>
</div>
""", unsafe_allow_html=True)

    st.markdown('<div style="font-size:0.65rem;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.14em;padding:0 0 4px;font-weight:400">Navegação</div>', unsafe_allow_html=True)

menu_map_total = {
    "🏠 Dashboard": "Dashboard",
    "📅 Agenda": "Agenda",
    "🐎 Cadastrar Animal": "Cadastrar Animal",
    "📋 Animais por Tipo": "Animais por Tipo",
    "⚖️ Pesagem / Evolução": "Pesagem / Evolução",
    "💉 Controle Sanitário": "Controle Sanitário",
    "💊 Farmácia": "Farmácia",
    "🌾 Ração": "Ração",
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
# AGENDA / CALENDÁRIO
# =========================================================

TIPOS_EVENTO = [
    "💉 Vacina / Vermifugação",
    "🩺 Consulta Veterinária",
    "🔁 Retorno Veterinário",
    "💊 Medicação",
    "⚖️ Pesagem",
    "🧬 Reprodução / Lavagem",
    "🐣 Parto Previsto",
    "🔨 Manutenção",
    "💰 Pagamento / Recebimento",
    "👥 Reunião / Visita",
    "📋 Outro",
]

CORES_EVENTO = {
    "💉 Vacina / Vermifugação":    "#4a9e6b",
    "🩺 Consulta Veterinária":     "#4a8fcf",
    "🔁 Retorno Veterinário":      "#7a6fcf",
    "💊 Medicação":                "#e8b84b",
    "⚖️ Pesagem":                  "#d4af50",
    "🧬 Reprodução / Lavagem":     "#cf4a8f",
    "🐣 Parto Previsto":           "#3db86a",
    "🔨 Manutenção":               "#8a9bb0",
    "💰 Pagamento / Recebimento":  "#4a9e6b",
    "👥 Reunião / Visita":         "#d4af50",
    "📋 Outro":                    "#6a7a8a",
}


def _cor_evento(tipo):
    return CORES_EVENTO.get(tipo, "#6a7a8a")


@st.cache_data(ttl=30)
def _carregar_agenda(ano, mes):
    """Carrega eventos do mês especificado."""
    try:
        df = pd.read_sql_query(
            "SELECT * FROM agenda WHERE data IS NOT NULL ORDER BY data, hora_inicio",
            get_engine()
        )
        if df.empty:
            return df
        df["data_dt"] = pd.to_datetime(df["data"], format="%d/%m/%Y", errors="coerce")
        df = df[df["data_dt"].notna()]
        df = df[(df["data_dt"].dt.year == ano) & (df["data_dt"].dt.month == mes)]
        return df
    except Exception:
        return pd.DataFrame()


def _calendario_html(ano, mes, eventos_df):
    """Gera o HTML do calendário mensal."""
    import calendar
    cal = calendar.monthcalendar(ano, mes)
    meses_pt = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    dias_semana = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

    # Mapeia eventos por dia
    ev_por_dia = {}
    if not eventos_df.empty:
        for _, row in eventos_df.iterrows():
            dia = row["data_dt"].day
            if dia not in ev_por_dia:
                ev_por_dia[dia] = []
            ev_por_dia[dia].append(row)

    hoje = date.today()
    css = """
<style>
.cal-wrap { font-family:'DM Sans',sans-serif; }
.cal-header { display:flex; align-items:center; justify-content:space-between;
  margin-bottom:16px; }
.cal-month { font-family:'Playfair Display',serif; font-size:1.3rem;
  font-weight:500; color:#e8e2d5; }
.cal-grid { display:grid; grid-template-columns:repeat(7,1fr); gap:4px; }
.cal-dow { text-align:center; font-size:0.68rem; color:rgba(212,175,80,0.5);
  text-transform:uppercase; letter-spacing:0.1em; padding:6px 0; font-weight:400; }
.cal-day { background:#0d1f3c; border:1px solid rgba(212,175,80,0.1);
  border-radius:10px; min-height:80px; padding:6px; position:relative;
  transition:border-color .15s; }
.cal-day:hover { border-color:rgba(212,175,80,0.3); }
.cal-day.empty { background:transparent; border-color:transparent; }
.cal-day.hoje { border-color:#d4af50; background:#0f2444; }
.cal-day.hoje .cal-num { color:#d4af50; }
.cal-num { font-size:0.78rem; font-weight:500; color:#7a8fa3; margin-bottom:4px; }
.cal-ev { font-size:0.65rem; color:#0a1628; border-radius:4px; padding:2px 5px;
  margin-bottom:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  font-weight:500; line-height:1.4; }
.cal-more { font-size:0.6rem; color:#5a7a6a; }
</style>
"""
    html = css + '<div class="cal-wrap">'
    html += f'<div class="cal-header"><div class="cal-month">{meses_pt[mes]} {ano}</div></div>'
    html += '<div class="cal-grid">'

    for d in dias_semana:
        html += f'<div class="cal-dow">{d}</div>'

    for semana in cal:
        for dia in semana:
            if dia == 0:
                html += '<div class="cal-day empty"></div>'
            else:
                classes = "cal-day"
                if hoje.year == ano and hoje.month == mes and hoje.day == dia:
                    classes += " hoje"
                html += f'<div class="{classes}">'
                html += f'<div class="cal-num">{dia}</div>'
                evs = ev_por_dia.get(dia, [])
                for ev in evs[:3]:
                    cor = _cor_evento(ev.get("tipo", ""))
                    titulo = str(ev.get("titulo", ""))[:22]
                    html += f'<div class="cal-ev" style="background:{cor}">{titulo}</div>'
                if len(evs) > 3:
                    html += f'<div class="cal-more">+{len(evs)-3} mais</div>'
                html += '</div>'

    html += '</div></div>'
    return html


if op == "Agenda":
    titulo_pagina("📅 Agenda", "Calendário de eventos, procedimentos e compromissos do haras")

    aba = st.radio(
        "Opção",
        ["📆 Calendário", "➕ Novo Evento", "📋 Lista de Eventos"],
        horizontal=True
    )

    animais_ag = listar_animais()
    funcionarios_ag = pd.read_sql_query(
        "SELECT * FROM funcionarios WHERE nome IS NOT NULL AND nome != '' AND status = 'Ativo'",
        conn
    )

    # ── CALENDÁRIO ─────────────────────────────────────────
    if aba == "📆 Calendário":
        col_nav1, col_nav2, col_nav3 = st.columns([1, 2, 1])

        if "agenda_ano" not in st.session_state:
            st.session_state.agenda_ano = date.today().year
        if "agenda_mes" not in st.session_state:
            st.session_state.agenda_mes = date.today().month

        with col_nav1:
            if st.button("← Mês anterior", use_container_width=True):
                if st.session_state.agenda_mes == 1:
                    st.session_state.agenda_mes = 12
                    st.session_state.agenda_ano -= 1
                else:
                    st.session_state.agenda_mes -= 1
                st.rerun()

        with col_nav3:
            if st.button("Próximo mês →", use_container_width=True):
                if st.session_state.agenda_mes == 12:
                    st.session_state.agenda_mes = 1
                    st.session_state.agenda_ano += 1
                else:
                    st.session_state.agenda_mes += 1
                st.rerun()

        with col_nav2:
            if st.button("📅 Hoje", use_container_width=True):
                st.session_state.agenda_ano = date.today().year
                st.session_state.agenda_mes = date.today().month
                st.rerun()

        ano_sel = st.session_state.agenda_ano
        mes_sel = st.session_state.agenda_mes

        df_mes = _carregar_agenda(ano_sel, mes_sel)

        # Calendário visual
        st.markdown(
            _calendario_html(ano_sel, mes_sel, df_mes),
            unsafe_allow_html=True
        )

        # Legenda de cores
        st.markdown("---")
        st.markdown("**Legenda de tipos:**")
        cols_leg = st.columns(4)
        for i, (tipo, cor) in enumerate(CORES_EVENTO.items()):
            with cols_leg[i % 4]:
                st.markdown(
                    f'<span style="display:inline-block;width:10px;height:10px;'
                    f'background:{cor};border-radius:3px;margin-right:5px"></span>'
                    f'<span style="font-size:0.78rem;color:#7a8fa3">{tipo}</span>',
                    unsafe_allow_html=True
                )

        # Eventos do dia selecionado
        st.markdown("---")
        st.markdown("### Eventos do mês")

        if df_mes.empty:
            st.info("Nenhum evento cadastrado para este mês.")
        else:
            for _, ev in df_mes.sort_values("data_dt").iterrows():
                cor = _cor_evento(ev.get("tipo", ""))
                status_ev = ev.get("status", "Agendado")
                status_cor = "#4a9e6b" if status_ev == "Concluído" else ("#e05252" if status_ev == "Cancelado" else "#e8b84b")

                st.markdown(f"""
<div style="background:#0d1f3c;border:1px solid rgba(212,175,80,0.1);border-left:3px solid {cor};
border-radius:0 10px 10px 0;padding:12px 16px;margin-bottom:8px;display:flex;
align-items:center;justify-content:space-between;gap:12px">
  <div style="flex:1">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
      <span style="font-size:0.9rem;font-weight:500;color:#e8e2d5">{ev.get('titulo','')}</span>
      <span style="font-size:0.68rem;background:{status_cor}22;color:{status_cor};
        border:1px solid {status_cor}44;border-radius:99px;padding:1px 8px">{status_ev}</span>
    </div>
    <div style="font-size:0.78rem;color:#5a7a6a">
      📅 {ev.get('data','')} &nbsp;·&nbsp;
      🕐 {ev.get('hora_inicio','')}{'–'+ev.get('hora_fim','') if ev.get('hora_fim') else ''} &nbsp;·&nbsp;
      {ev.get('tipo','')}
    </div>
    <div style="font-size:0.78rem;color:#7a8fa3;margin-top:2px">
      {'🐎 '+ev.get('animal','') if ev.get('animal') else ''}
      {'&nbsp;·&nbsp; 👤 '+ev.get('funcionario','') if ev.get('funcionario') else ''}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── NOVO EVENTO ────────────────────────────────────────
    elif aba == "➕ Novo Evento":
        titulo_pagina("➕ Novo Evento", "Cadastre um compromisso, procedimento ou tarefa")

        col1, col2 = st.columns(2)

        with col1:
            titulo_ev = st.text_input("Título do evento *")
            tipo_ev = st.selectbox("Tipo", TIPOS_EVENTO)
            data_ev = st.date_input("Data *", format="DD/MM/YYYY")
            col_h1, col_h2 = st.columns(2)
            with col_h1:
                hora_inicio = st.time_input("Hora início")
            with col_h2:
                hora_fim = st.time_input("Hora fim", value=None)

        with col2:
            animal_ev = ""
            if not animais_ag.empty:
                opcoes_animal = ["(nenhum)"] + animais_ag["nome"].dropna().tolist()
                sel_animal = st.selectbox("Animal (opcional)", opcoes_animal)
                animal_ev = sel_animal if sel_animal != "(nenhum)" else ""
            else:
                st.info("Nenhum animal cadastrado.")

            funcionario_ev = ""
            if not funcionarios_ag.empty:
                opcoes_func = ["(nenhum)"] + funcionarios_ag["nome"].dropna().tolist()
                sel_func = st.selectbox("Responsável (opcional)", opcoes_func)
                funcionario_ev = sel_func if sel_func != "(nenhum)" else ""
            else:
                st.info("Nenhum funcionário ativo.")

            status_ev = st.selectbox("Status", ["Agendado", "Concluído", "Cancelado"])
            descricao_ev = st.text_area("Descrição / observações")

        if st.button("💾 Salvar Evento", use_container_width=True):
            if not titulo_ev:
                st.error("Informe o título do evento.")
            else:
                hora_fim_str = hora_fim.strftime("%H:%M") if hora_fim else ""
                c.execute("""
                    INSERT INTO agenda
                    (titulo, tipo, data, hora_inicio, hora_fim,
                     animal, funcionario, descricao, status, cor, obs)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    titulo_ev,
                    tipo_ev,
                    br_data(data_ev),
                    hora_inicio.strftime("%H:%M"),
                    hora_fim_str,
                    animal_ev,
                    funcionario_ev,
                    descricao_ev,
                    status_ev,
                    _cor_evento(tipo_ev),
                    ""
                ))
                conn.commit()
                _carregar_agenda.clear()
                st.success(f"✅ Evento '{titulo_ev}' salvo para {br_data(data_ev)}!")
                st.session_state.agenda_ano = data_ev.year
                st.session_state.agenda_mes = data_ev.month

    # ── LISTA DE EVENTOS ───────────────────────────────────
    elif aba == "📋 Lista de Eventos":
        titulo_pagina("📋 Lista de Eventos", "Todos os eventos cadastrados")

        try:
            df_todos = pd.read_sql_query(
                "SELECT * FROM agenda WHERE data IS NOT NULL ORDER BY data DESC, hora_inicio",
                get_engine()
            )
        except Exception:
            df_todos = pd.DataFrame()

        if df_todos.empty:
            st.info("Nenhum evento cadastrado ainda.")
        else:
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                filtro_tipo = st.selectbox("Filtrar tipo", ["Todos"] + TIPOS_EVENTO)
            with col_f2:
                filtro_status = st.selectbox("Filtrar status", ["Todos", "Agendado", "Concluído", "Cancelado"])
            with col_f3:
                filtro_animal = st.text_input("Buscar animal")

            df_v = df_todos.copy()
            if filtro_tipo != "Todos":
                df_v = df_v[df_v["tipo"] == filtro_tipo]
            if filtro_status != "Todos":
                df_v = df_v[df_v["status"] == filtro_status]
            if filtro_animal:
                df_v = df_v[df_v["animal"].fillna("").str.contains(filtro_animal, case=False)]

            st.metric("Eventos encontrados", len(df_v))

            # Exibe lista com ações
            for _, ev in df_v.iterrows():
                cor = _cor_evento(ev.get("tipo", ""))
                status_ev = ev.get("status", "Agendado")
                status_cor = "#4a9e6b" if status_ev == "Concluído" else ("#e05252" if status_ev == "Cancelado" else "#e8b84b")
                ev_id = str(ev["id"])

                colA, colB, colC = st.columns([5, 1, 1])
                with colA:
                    st.markdown(f"""
<div style="background:#0d1f3c;border:1px solid rgba(212,175,80,0.1);border-left:3px solid {cor};
border-radius:0 10px 10px 0;padding:10px 16px;margin-bottom:4px">
  <div style="display:flex;align-items:center;gap:8px">
    <span style="font-size:0.88rem;font-weight:500;color:#e8e2d5">{ev.get('titulo','')}</span>
    <span style="font-size:0.65rem;background:{status_cor}22;color:{status_cor};
      border:1px solid {status_cor}44;border-radius:99px;padding:1px 7px">{status_ev}</span>
  </div>
  <div style="font-size:0.75rem;color:#5a7a6a;margin-top:3px">
    📅 {ev.get('data','')} · 🕐 {ev.get('hora_inicio','')} · {ev.get('tipo','')}
    {'· 🐎 '+ev.get('animal','') if ev.get('animal') else ''}
    {'· 👤 '+ev.get('funcionario','') if ev.get('funcionario') else ''}
  </div>
</div>
""", unsafe_allow_html=True)

                with colB:
                    if status_ev != "Concluído":
                        if st.button("✅", key=f"conc_{ev_id}", help="Marcar como concluído"):
                            c.execute("UPDATE agenda SET status = %s WHERE id = %s", ("Concluído", ev_id))
                            conn.commit()
                            _carregar_agenda.clear()
                            st.rerun()

                with colC:
                    if st.button("🗑️", key=f"del_{ev_id}", help="Excluir evento"):
                        c.execute("DELETE FROM agenda WHERE id = %s", (ev_id,))
                        conn.commit()
                        _carregar_agenda.clear()
                        st.rerun()

            st.markdown("---")
            st.download_button(
                "📥 Baixar Eventos (Excel)",
                data=gerar_excel(df_v),
                file_name="agenda_rancho_recanto_verde.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    # ── Importa automaticamente da medicacoes_agendadas ──────
    with st.expander("🔄 Sincronizar com Medicações Agendadas", expanded=False):
        st.caption("Importa automaticamente as medicações agendadas do módulo Veterinário para a Agenda.")
        if st.button("🔄 Sincronizar agora", use_container_width=True):
            try:
                meds = pd.read_sql_query(
                    "SELECT * FROM medicacoes_agendadas WHERE status = 'Agendada' AND data_hora IS NOT NULL",
                    get_engine()
                )
                importados = 0
                for _, m in meds.iterrows():
                    try:
                        dh = datetime.strptime(str(m["data_hora"]), "%d/%m/%Y %H:%M")
                        titulo_m = f"💊 {m['medicamento']} — {m['animal']}"
                        existente = pd.read_sql_query(
                            "SELECT id FROM agenda WHERE titulo = %s AND data = %s",
                            get_engine(),
                            params=(titulo_m, dh.strftime("%d/%m/%Y"))
                        )
                        if existente.empty:
                            c.execute("""
                                INSERT INTO agenda
                                (titulo, tipo, data, hora_inicio, hora_fim,
                                 animal, funcionario, descricao, status, cor, obs)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                titulo_m,
                                "💊 Medicação",
                                dh.strftime("%d/%m/%Y"),
                                dh.strftime("%H:%M"),
                                "",
                                str(m.get("animal", "")),
                                str(m.get("funcionario", "")),
                                str(m.get("dosagem", "")),
                                "Agendado",
                                _cor_evento("💊 Medicação"),
                                ""
                            ))
                            importados += 1
                    except Exception:
                        continue
                conn.commit()
                _carregar_agenda.clear()
                st.success(f"✅ {importados} medicação(ões) importada(s) para a Agenda!")
            except Exception as e:
                st.error(f"Erro ao sincronizar: {e}")


# =========================================================
# RAÇÃO
# =========================================================

CATEGORIAS_RACAO = ["Ração", "Suplemento", "Sal Mineral", "Volumoso", "Outro"]
TURNOS = ["Manhã", "Tarde", "Noite"]

@st.cache_data(ttl=60)
def _carregar_estoque_racao():
    try:
        return pd.read_sql_query(
            "SELECT * FROM racao_estoque WHERE produto IS NOT NULL ORDER BY produto",
            get_engine()
        )
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=60)
def _carregar_dieta():
    try:
        return pd.read_sql_query(
            "SELECT * FROM racao_dieta WHERE animal IS NOT NULL AND ativo = 'Sim'",
            get_engine()
        )
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=30)
def _carregar_fornecimento(mes, ano):
    try:
        df = pd.read_sql_query(
            "SELECT * FROM racao_fornecimento WHERE data IS NOT NULL ORDER BY data DESC",
            get_engine()
        )
        if df.empty:
            return df
        df["data_dt"] = pd.to_datetime(df["data"], format="%d/%m/%Y", errors="coerce")
        return df[(df["data_dt"].dt.month == mes) & (df["data_dt"].dt.year == ano)]
    except Exception:
        return pd.DataFrame()


if op == "Ração":
    titulo_pagina("🌾 Controle de Ração", "Estoque, dietas e fornecimento por animal")

    aba = st.radio("Opção", [
        "📊 Dashboard Ração",
        "🛒 Estoque / Compras",
        "🍽️ Dietas por Animal",
        "✅ Registrar Fornecimento",
        "📋 Histórico",
    ], horizontal=True)

    animais_r = listar_animais(somente_ativos=True)

    # ── DASHBOARD RAÇÃO ─────────────────────────────────
    if aba == "📊 Dashboard Ração":
        titulo_pagina("📊 Dashboard de Ração", "Resumo do estoque e consumo mensal")

        est = _carregar_estoque_racao()
        dieta = _carregar_dieta()
        hoje = date.today()
        forn = _carregar_fornecimento(hoje.month, hoje.year)

        # Métricas
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Produtos em estoque", len(est) if not est.empty else 0)
        with m2:
            total_kg = pd.to_numeric(est["quantidade_kg"], errors="coerce").sum() if not est.empty else 0
            st.metric("Total em estoque (kg)", f"{total_kg:.1f} kg")
        with m3:
            animais_dieta = dieta["animal"].nunique() if not dieta.empty else 0
            st.metric("Animais com dieta", animais_dieta)
        with m4:
            consumo_mes = pd.to_numeric(forn["quantidade_kg"], errors="coerce").sum() if not forn.empty else 0
            st.metric("Consumo este mês (kg)", f"{consumo_mes:.1f} kg")

        st.markdown("---")

        # Alertas de estoque baixo
        if not est.empty:
            est["qtd_num"] = pd.to_numeric(est["quantidade_kg"], errors="coerce").fillna(0)
            est["min_num"] = pd.to_numeric(est["estoque_minimo"], errors="coerce").fillna(0)
            alertas = est[est["qtd_num"] <= est["min_num"]]

            if not alertas.empty:
                st.markdown(f"""
<div style='background:rgba(224,90,90,0.12);border:1px solid rgba(224,90,90,0.3);
border-left:4px solid #e05a5a;border-radius:10px;padding:14px 18px;margin-bottom:16px'>
  <div style='font-weight:500;color:#e05a5a;margin-bottom:8px'>
    ⚠️ {len(alertas)} produto(s) com estoque baixo ou zerado!
  </div>
  {''.join(f"<div style='font-size:0.85rem;color:#f0ece3;margin-top:4px'>• {row['produto']} — {row['qtd_num']:.1f} kg restantes (mínimo: {row['min_num']:.1f} kg)</div>"
            for _, row in alertas.iterrows())}
</div>
""", unsafe_allow_html=True)
            else:
                st.success("✅ Todos os estoques estão acima do mínimo.")

        # Consumo por produto este mês
        if not forn.empty:
            st.markdown("### Consumo por produto este mês")
            consumo_prod = forn.groupby("produto")["quantidade_kg"].apply(
                lambda x: pd.to_numeric(x, errors="coerce").sum()
            ).reset_index()
            consumo_prod.columns = ["Produto", "Consumo (kg)"]
            consumo_prod["Consumo (kg)"] = consumo_prod["Consumo (kg)"].round(2)
            st.dataframe(consumo_prod, use_container_width=True, hide_index=True)

        # Dietas ativas
        if not dieta.empty:
            st.markdown("### Dietas ativas por animal")
            dieta_resumo = dieta.groupby("animal").apply(
                lambda x: ", ".join(f"{r['produto']} {r['quantidade_kg']}kg/{r['turno']}" for _, r in x.iterrows())
            ).reset_index()
            dieta_resumo.columns = ["Animal", "Dieta"]
            st.dataframe(dieta_resumo, use_container_width=True, hide_index=True)

    # ── ESTOQUE / COMPRAS ────────────────────────────────
    elif aba == "🛒 Estoque / Compras":
        titulo_pagina("🛒 Estoque de Ração", "Registre compras e gerencie o estoque")

        with st.expander("➕ Registrar nova compra", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                r_produto   = st.text_input("Nome do produto *", placeholder="Ex: Ração Equilíbrio Senior")
                r_categoria = st.selectbox("Categoria", CATEGORIAS_RACAO)
                r_qtd       = st.number_input("Quantidade comprada (kg) *", min_value=0.0, step=0.5)
                r_unidade   = st.selectbox("Unidade de compra", ["kg", "saco 30kg", "saco 40kg", "saco 50kg", "fardo"])
            with col2:
                r_data      = st.date_input("Data da compra *", format="DD/MM/YYYY")
                r_validade  = st.date_input("Validade", format="DD/MM/YYYY", value=None)
                r_fornecedor= st.text_input("Fornecedor")
                r_preco     = st.number_input("Preço total (R$)", min_value=0.0, step=0.01)
                r_estmin    = st.number_input("Estoque mínimo (kg)", min_value=0.0, step=0.5, value=50.0)
                r_obs       = st.text_input("Observações")

            if st.button("💾 Registrar compra", use_container_width=True):
                if not r_produto or r_qtd <= 0:
                    st.error("Informe o produto e a quantidade.")
                else:
                    preco_kg = round(r_preco / r_qtd, 4) if r_qtd > 0 else 0
                    # Verifica se produto já existe e soma estoque
                    existe = pd.read_sql_query(
                        "SELECT id, quantidade_kg FROM racao_estoque WHERE produto = %s",
                        get_engine(), params=(r_produto,)
                    )
                    if not existe.empty:
                        qtd_atual = float(existe.iloc[0]["quantidade_kg"] or 0)
                        c.execute(
                            "UPDATE racao_estoque SET quantidade_kg = %s, data_compra = %s, preco_total = %s, preco_kg = %s WHERE produto = %s",
                            (str(qtd_atual + r_qtd), br_data(r_data), str(r_preco), str(preco_kg), r_produto)
                        )
                        msg = f"✅ Estoque de '{r_produto}' atualizado! Total: {qtd_atual + r_qtd:.1f} kg"
                    else:
                        c.execute("""
                            INSERT INTO racao_estoque
                            (produto, categoria, quantidade_kg, unidade, data_compra,
                             validade, fornecedor, preco_total, preco_kg, estoque_minimo, obs)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """, (
                            r_produto, r_categoria, str(r_qtd), r_unidade,
                            br_data(r_data),
                            br_data(r_validade) if r_validade else "",
                            r_fornecedor, str(r_preco), str(preco_kg),
                            str(r_estmin), r_obs
                        ))
                        msg = f"✅ Produto '{r_produto}' cadastrado com {r_qtd:.1f} kg!"
                    conn.commit()
                    _carregar_estoque_racao.clear()
                    registrar_auditoria("Ração", "Compra", f"Produto '{r_produto}' registrado no estoque")
                    st.success(msg)
                    st.rerun()

        # Lista estoque atual
        est = _carregar_estoque_racao()
        if not est.empty:
            st.markdown("### Estoque atual")
            est["qtd_num"] = pd.to_numeric(est["quantidade_kg"], errors="coerce").fillna(0)
            est["min_num"] = pd.to_numeric(est["estoque_minimo"], errors="coerce").fillna(0)
            est["Status"] = est.apply(
                lambda r: "🔴 Crítico" if r["qtd_num"] == 0
                else ("🟡 Baixo" if r["qtd_num"] <= r["min_num"] else "🟢 OK"), axis=1
            )
            cols_show = ["produto", "categoria", "quantidade_kg", "unidade", "estoque_minimo", "preco_kg", "data_compra", "Status"]
            cols_show = [c0 for c0 in cols_show if c0 in est.columns]
            st.dataframe(est[cols_show].rename(columns={
                "produto": "Produto", "categoria": "Categoria",
                "quantidade_kg": "Estoque (kg)", "unidade": "Unidade",
                "estoque_minimo": "Mínimo (kg)", "preco_kg": "R$/kg",
                "data_compra": "Última compra"
            }), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum produto cadastrado. Registre sua primeira compra acima.")

    # ── DIETAS POR ANIMAL ────────────────────────────────
    elif aba == "🍽️ Dietas por Animal":
        titulo_pagina("🍽️ Dietas por Animal", "Configure a ração fixa diária de cada animal")

        if animais_r.empty:
            st.warning("Nenhum animal ativo cadastrado.")
        else:
            est = _carregar_estoque_racao()
            produtos_disponiveis = est["produto"].tolist() if not est.empty else []

            if not produtos_disponiveis:
                st.warning("Cadastre produtos no estoque primeiro.")
            else:
                col1, col2 = st.columns(2)
                with col1:
                    animal_d = st.selectbox("Animal *", animais_r["nome"].tolist(), key="dieta_animal")
                    produto_d = st.selectbox("Produto *", produtos_disponiveis, key="dieta_prod")
                    qtd_d = st.number_input("Quantidade por fornecimento (kg) *", min_value=0.1, step=0.1, value=2.0)
                with col2:
                    turno_d = st.selectbox("Turno", TURNOS, key="dieta_turno")
                    obs_d = st.text_input("Observação", key="dieta_obs")

                if st.button("💾 Salvar dieta", use_container_width=True):
                    # Verifica se já tem dieta para esse animal+produto+turno
                    existe = pd.read_sql_query(
                        "SELECT id FROM racao_dieta WHERE animal = %s AND produto = %s AND turno = %s",
                        get_engine(), params=(animal_d, produto_d, turno_d)
                    )
                    if not existe.empty:
                        c.execute(
                            "UPDATE racao_dieta SET quantidade_kg = %s, ativo = 'Sim', obs = %s WHERE id = %s",
                            (str(qtd_d), obs_d, str(existe.iloc[0]["id"]))
                        )
                    else:
                        c.execute(
                            "INSERT INTO racao_dieta (animal, produto, quantidade_kg, turno, ativo, obs) VALUES (%s,%s,%s,%s,%s,%s)",
                            (animal_d, produto_d, str(qtd_d), turno_d, "Sim", obs_d)
                        )
                    conn.commit()
                    _carregar_dieta.clear()
                    st.success(f"✅ Dieta de {animal_d} salva: {qtd_d}kg de {produto_d} no {turno_d}!")
                    st.rerun()

            # Lista dietas atuais
            dieta = _carregar_dieta()
            if not dieta.empty:
                st.markdown("---")
                st.markdown("### Dietas ativas")
                for animal_nome in dieta["animal"].unique():
                    df_an = dieta[dieta["animal"] == animal_nome]
                    total_dia = pd.to_numeric(df_an["quantidade_kg"], errors="coerce").sum() * len(df_an["turno"].unique())
                    st.markdown(f"""
<div style='background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--gold);
border-radius:0 10px 10px 0;padding:12px 16px;margin-bottom:8px'>
  <div style='font-weight:500;color:var(--text);margin-bottom:6px'>🐎 {animal_nome} — {total_dia:.1f} kg/dia total</div>
  {''.join(f"<div style='font-size:0.82rem;color:var(--muted);margin-top:2px'>• {r['turno']}: {r['produto']} — {r['quantidade_kg']} kg</div>" for _, r in df_an.iterrows())}
</div>
""", unsafe_allow_html=True)

                    col_btn1, col_btn2 = st.columns([4, 1])
                    with col_btn2:
                        if st.button("❌ Desativar todas", key=f"desativ_{animal_nome}"):
                            c.execute("UPDATE racao_dieta SET ativo = 'Não' WHERE animal = %s", (animal_nome,))
                            conn.commit()
                            _carregar_dieta.clear()
                            st.rerun()
            else:
                st.info("Nenhuma dieta cadastrada ainda.")

    # ── REGISTRAR FORNECIMENTO ───────────────────────────
    elif aba == "✅ Registrar Fornecimento":
        titulo_pagina("✅ Registrar Fornecimento", "Registre o que foi fornecido hoje")

        dieta = _carregar_dieta()
        est = _carregar_estoque_racao()

        col1, col2 = st.columns(2)
        with col1:
            data_forn = st.date_input("Data *", value=date.today(), format="DD/MM/YYYY")
            turno_forn = st.selectbox("Turno *", TURNOS)
        with col2:
            responsavel_forn = st.text_input("Responsável")

        # Botão para pré-preencher com dieta do dia
        if not dieta.empty:
            dieta_turno = dieta[dieta["turno"] == turno_forn]
            if not dieta_turno.empty and st.button("⚡ Pré-preencher com dieta do turno", use_container_width=True):
                st.session_state["prefill_forn"] = dieta_turno.to_dict("records")

        st.markdown("---")
        st.markdown("### Animais e quantidades")

        # Monta lista de fornecimentos
        if animais_r.empty:
            st.warning("Nenhum animal ativo.")
        else:
            produtos_est = est["produto"].tolist() if not est.empty else []
            fornecimentos = []
            prefill = st.session_state.get("prefill_forn", [])

            for _, animal in animais_r.iterrows():
                nome_an = animal["nome"]
                # Verifica se tem dieta para esse animal neste turno
                dieta_an = dieta[(dieta["animal"] == nome_an) & (dieta["turno"] == turno_forn)] if not dieta.empty else pd.DataFrame()

                with st.expander(f"🐎 {nome_an}", expanded=not dieta_an.empty):
                    if not dieta_an.empty:
                        for _, d in dieta_an.iterrows():
                            col_a, col_b, col_c = st.columns([2, 1, 1])
                            with col_a:
                                prod_sel = st.selectbox(
                                    "Produto", produtos_est,
                                    index=produtos_est.index(d["produto"]) if d["produto"] in produtos_est else 0,
                                    key=f"fp_{nome_an}_{d['turno']}_{d['produto']}"
                                )
                            with col_b:
                                qtd_sel = st.number_input(
                                    "kg", min_value=0.0, step=0.1,
                                    value=float(d["quantidade_kg"] or 0),
                                    key=f"fq_{nome_an}_{d['turno']}_{d['produto']}"
                                )
                            with col_c:
                                fornecer = st.checkbox("Fornecer", value=True, key=f"fc_{nome_an}_{d['turno']}_{d['produto']}")

                            if fornecer and qtd_sel > 0:
                                fornecimentos.append((nome_an, prod_sel, qtd_sel))
                    else:
                        # Animal sem dieta — permite adicionar manualmente
                        col_a, col_b = st.columns([2, 1])
                        with col_a:
                            prod_man = st.selectbox("Produto", ["(nenhum)"] + produtos_est, key=f"pm_{nome_an}")
                        with col_b:
                            qtd_man = st.number_input("kg", min_value=0.0, step=0.1, key=f"qm_{nome_an}")
                        if prod_man != "(nenhum)" and qtd_man > 0:
                            fornecimentos.append((nome_an, prod_man, qtd_man))

            if st.button("💾 Confirmar fornecimento", use_container_width=True):
                if not fornecimentos:
                    st.error("Nenhum item para registrar.")
                else:
                    erros_estoque = []
                    for nome_an, prod, qtd in fornecimentos:
                        # Desconta do estoque
                        est_prod = pd.read_sql_query(
                            "SELECT id, quantidade_kg FROM racao_estoque WHERE produto = %s",
                            get_engine(), params=(prod,)
                        )
                        if not est_prod.empty:
                            qtd_atual = float(est_prod.iloc[0]["quantidade_kg"] or 0)
                            nova_qtd = max(0, qtd_atual - qtd)
                            c.execute(
                                "UPDATE racao_estoque SET quantidade_kg = %s WHERE produto = %s",
                                (str(nova_qtd), prod)
                            )
                            if qtd > qtd_atual:
                                erros_estoque.append(f"{prod}: solicitado {qtd}kg, disponível {qtd_atual}kg")

                        # Registra fornecimento
                        c.execute("""
                            INSERT INTO racao_fornecimento
                            (animal, produto, quantidade_kg, turno, data, responsavel, obs)
                            VALUES (%s,%s,%s,%s,%s,%s,%s)
                        """, (nome_an, prod, str(qtd), turno_forn, br_data(data_forn), responsavel_forn, ""))

                    conn.commit()
                    _carregar_estoque_racao.clear()
                    _carregar_fornecimento.clear()
                    st.session_state.pop("prefill_forn", None)

                    if erros_estoque:
                        st.warning("⚠️ Fornecimento registrado, mas estoque insuficiente para: " + "; ".join(erros_estoque))
                    else:
                        st.success(f"✅ {len(fornecimentos)} fornecimento(s) registrado(s) e estoque atualizado!")
                    st.rerun()

    # ── HISTÓRICO ────────────────────────────────────────
    elif aba == "📋 Histórico":
        titulo_pagina("📋 Histórico de Fornecimento", "Consulte o histórico por período")

        col1, col2, col3 = st.columns(3)
        with col1:
            mes_h = st.selectbox("Mês", list(range(1, 13)), index=date.today().month - 1,
                                  format_func=lambda m: ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"][m-1])
        with col2:
            ano_h = st.selectbox("Ano", list(range(2024, date.today().year + 2)), index=1)
        with col3:
            filtro_animal_h = st.text_input("Filtrar animal")

        df_hist = _carregar_fornecimento(mes_h, ano_h)

        if not df_hist.empty:
            if filtro_animal_h:
                df_hist = df_hist[df_hist["animal"].str.contains(filtro_animal_h, case=False, na=False)]

            # Resumo
            total_kg_h = pd.to_numeric(df_hist["quantidade_kg"], errors="coerce").sum()
            m1, m2, m3 = st.columns(3)
            with m1: st.metric("Registros", len(df_hist))
            with m2: st.metric("Total fornecido (kg)", f"{total_kg_h:.1f}")
            with m3: st.metric("Animais atendidos", df_hist["animal"].nunique())

            st.dataframe(
                df_hist[["data", "turno", "animal", "produto", "quantidade_kg", "responsavel"]].rename(columns={
                    "data": "Data", "turno": "Turno", "animal": "Animal",
                    "produto": "Produto", "quantidade_kg": "kg", "responsavel": "Responsável"
                }),
                use_container_width=True, hide_index=True
            )

            st.download_button(
                "📥 Baixar Excel",
                data=gerar_excel(df_hist),
                file_name=f"racao_{mes_h:02d}_{ano_h}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("Nenhum fornecimento registrado neste período.")


# =========================================================
# DASHBOARD - HOME ESTILO APP PROFISSIONAL
# =========================================================

if op == "Dashboard":
    animais, farmacia, sanitario, tratamentos, vendas, recebimentos, receptoras = _carregar_dashboard()

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

    st.markdown("""
<div style='display:flex;align-items:center;gap:14px;margin-bottom:20px'>
  <div style='width:4px;height:48px;border-radius:99px;background:linear-gradient(180deg,#c9a84c,#1a7a4a);flex-shrink:0'></div>
  <div>
    <div style='font-family:"Playfair Display",serif;font-size:1.5rem;font-weight:500;color:#f0ece3;margin:0;line-height:1.1'>Rancho Recanto Verde</div>
    <div style='font-size:0.82rem;color:#9ab8a8;font-weight:300;margin-top:2px'>Gestão completa do haras na palma da mão</div>
  </div>
</div>
<div style='height:2px;background:linear-gradient(90deg,#c9a84c,rgba(26,122,74,0.3),transparent);margin-bottom:20px;border-radius:99px'></div>
""", unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.68rem;color:#9ab8a8;text-transform:uppercase;letter-spacing:0.14em;font-weight:500;margin-bottom:10px">⚡ Acesso rápido</div>', unsafe_allow_html=True)

    linha1 = st.columns(4)
    atalhos = [
        ("🐎", "Animais", "Cadastros e histórico", "Animais por Tipo"),
        ("💉", "Saúde", "Vacinas e vermífugos", "Controle Sanitário"),
        ("💊", "Farmácia", "Estoque e custos", "Farmácia"),
        ("💰", "Financeiro", "Vendas e recebimentos", "Vendas de Animais"),
    ]

    for col, (icone, titulo, subtitulo, pagina) in zip(linha1, atalhos):
        with col:
            if st.button(f"{icone}\n{titulo}\n{subtitulo}", key=f"atalho_{pagina}", use_container_width=True):
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
            if st.button(f"{icone}\n{titulo}\n{subtitulo}", key=f"atalho_{pagina}", use_container_width=True):
                st.session_state.pagina_atual = pagina
                st.rerun()

    st.markdown("""
<div style='margin:22px 0 16px'>
  <div style='height:1px;background:linear-gradient(90deg,#c9a84c,rgba(26,122,74,0.3),transparent);margin-bottom:16px;border-radius:99px'></div>
  <div style='font-size:0.68rem;color:#9ab8a8;text-transform:uppercase;letter-spacing:0.14em;font-weight:500'>
    📊 Resumo do haras
  </div>
</div>
""", unsafe_allow_html=True)

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
    # ── Alerta de aplicações pendentes de confirmação ────────
    try:
        pend_san = pd.read_sql_query(
            "SELECT COUNT(*) as total FROM sanitario WHERE (status_aplicacao = 'Agendado' OR status_aplicacao IS NULL OR status_aplicacao = '') AND produto IS NOT NULL",
            get_engine()
        ).iloc[0]["total"]
        pend_vet = pd.read_sql_query(
            "SELECT COUNT(*) as total FROM ficha_medicacoes WHERE (status = 'Agendada' OR status IS NULL OR status = '') AND medicamento IS NOT NULL",
            get_engine()
        ).iloc[0]["total"]
        total_pend = int(pend_san or 0) + int(pend_vet or 0)
        if total_pend > 0:
            st.markdown(f"""
<div style='background:rgba(232,184,75,0.1);border:1px solid rgba(232,184,75,0.3);
border-left:4px solid #e8b84b;border-radius:0 10px 10px 0;
padding:12px 16px;margin-bottom:14px;display:flex;justify-content:space-between;align-items:center'>
  <div>
    <div style='font-weight:500;color:#e8b84b;font-size:0.92rem'>
      ⏳ {total_pend} aplicação(ões) aguardando confirmação
    </div>
    <div style='font-size:0.78rem;color:var(--muted);margin-top:2px'>
      {'💉 '+str(pend_san)+' sanitária(s)' if pend_san else ''}{' &nbsp;·&nbsp; ' if pend_san and pend_vet else ''}{'🩺 '+str(pend_vet)+' veterinária(s)' if pend_vet else ''}
      &nbsp;·&nbsp; Estoque NÃO foi baixado ainda
    </div>
  </div>
</div>
""", unsafe_allow_html=True)
    except Exception:
        pass

    # ── Próximos eventos da Agenda ──────────────────────────
    try:
        df_prox = pd.read_sql_query(
            "SELECT * FROM agenda WHERE status = 'Agendado' AND data IS NOT NULL ORDER BY data, hora_inicio LIMIT 5",
            get_engine()
        )
        if not df_prox.empty:
            df_prox["data_dt"] = pd.to_datetime(df_prox["data"], format="%d/%m/%Y", errors="coerce")
            df_prox = df_prox[df_prox["data_dt"] >= pd.Timestamp(date.today())]

        if not df_prox.empty:
            st.markdown("---")
            st.markdown("### 📅 Próximos eventos")
            for _, ev in df_prox.head(5).iterrows():
                cor = _cor_evento(ev.get("tipo", ""))
                dias_faltam = (ev["data_dt"].date() - date.today()).days
                label_dias = "Hoje" if dias_faltam == 0 else f"Em {dias_faltam}d"
                st.markdown(f"""
<div style="background:#0d1f3c;border:1px solid rgba(212,175,80,0.1);border-left:3px solid {cor};
border-radius:0 10px 10px 0;padding:10px 16px;margin-bottom:6px;display:flex;align-items:center;justify-content:space-between">
  <div>
    <span style="font-size:0.88rem;font-weight:500;color:#e8e2d5">{ev.get('titulo','')}</span>
    <div style="font-size:0.75rem;color:#5a7a6a;margin-top:2px">
      {ev.get('data','')} · {ev.get('hora_inicio','')} · {ev.get('tipo','')}
      {'· '+ev.get('animal','') if ev.get('animal') else ''}
    </div>
  </div>
  <span style="font-size:0.72rem;background:rgba(212,175,80,0.1);color:#d4af50;
    border:1px solid rgba(212,175,80,0.2);border-radius:99px;padding:3px 10px;white-space:nowrap">{label_dias}</span>
</div>
""", unsafe_allow_html=True)
            if st.button("Ver agenda completa →", key="dash_agenda"):
                st.session_state.pagina_atual = "Agenda"
                st.rerun()
    except Exception:
        pass

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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            nome, tipo, especie, raca, sexo, br_data(nascimento), cor,
            responsavel, cpf, telefone, local, microchip, status_animal,
            registro_abqm, nome_oficial_abqm, pai_abqm, mae_abqm,
            criador_abqm, proprietario_abqm, link_abqm, obs_abqm,
            obs
        ))
        conn.commit()
        listar_animais.clear()
        _carregar_dashboard.clear()
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
                "SELECT * FROM animais WHERE id = %s", get_engine(),
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
                        SET nome = %s, tipo = %s, especie = %s, raca = %s, sexo = %s,
                            nascimento = %s, cor = %s, responsavel = %s, cpf = %s,
                            telefone = %s, local = %s, microchip = %s, status = %s,
                            registro_abqm = %s, nome_oficial_abqm = %s, pai_abqm = %s,
                            mae_abqm = %s, criador_abqm = %s, proprietario_abqm = %s,
                            link_abqm = %s, obs_abqm = %s, obs = %s
                        WHERE id = %s
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
                    listar_animais.clear()
                    _carregar_dashboard.clear()
                    registrar_auditoria("Animais", "Alteração", f"Animal '{animal_nome}' alterado")
                    st.success("Animal alterado com sucesso!")
                    st.rerun()

            with col_btn2:
                confirmar = st.checkbox("Confirmar exclusão deste animal")
                if st.button("🗑️ Excluir Animal", use_container_width=True):
                    if confirmar:
                        c.execute("DELETE FROM animais WHERE id = %s", (animal_id,))
                        conn.commit()
                        listar_animais.clear()
                        _carregar_dashboard.clear()
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
                    VALUES (%s, %s, %s, %s, %s)
                """, (animal_nome, animal_tipo, br_data(data_pesagem), str(peso), obs))
                conn.commit()
                st.success("Pesagem registrada com sucesso!")

    elif aba == "Histórico de Pesagens":
        df = pd.read_sql_query("SELECT * FROM pesagens WHERE animal IS NOT NULL", get_engine())

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
        ["Registrar Vacina", "Registrar Vermifugação", "✅ Confirmar Aplicação", "Alertas Sanitários", "Histórico Sanitário"],
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

            if st.button("💾 Salvar Procedimento", use_container_width=True):
                if quantidade_usada <= 0:
                    st.error("Informe a quantidade usada.")
                else:
                    preco_unitario_calc = 0.0
                    med_ref = pd.read_sql_query(
                        "SELECT preco_por_controle, preco FROM farmacia WHERE medicamento = %s",
                        get_engine(), params=(produto,)
                    )
                    if not med_ref.empty:
                        preco_unitario_calc = float(med_ref.iloc[0].get("preco_por_controle") or med_ref.iloc[0].get("preco") or 0)

                    c.execute("""
                        INSERT INTO sanitario
                        (animal, tipo, procedimento, produto, data_aplicacao, proxima_dose,
                         quantidade_usada, unidade, preco_unitario, custo_total, responsavel, obs,
                         status_aplicacao)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        animal_nome, animal_tipo, procedimento, produto, br_data(data_aplicacao),
                        br_data(proxima_dose), str(quantidade_usada), unidade,
                        str(preco_unitario_calc), str(quantidade_usada * preco_unitario_calc),
                        responsavel, obs, "Agendado"
                    ))
                    conn.commit()
                    st.success(f"✅ {procedimento} registrado! Estoque será baixado quando confirmar a aplicação.")

    elif aba == "✅ Confirmar Aplicação":
        titulo_pagina("✅ Confirmar Aplicação", "Confirme que o medicamento/vacina foi aplicado — o estoque será baixado neste momento")

        # Busca todos os registros pendentes de confirmação
        try:
            df_pend = pd.read_sql_query("""
                SELECT id, animal, tipo, procedimento, produto, data_aplicacao,
                       quantidade_usada, unidade, responsavel, status_aplicacao
                FROM sanitario
                WHERE (status_aplicacao = 'Agendado' OR status_aplicacao IS NULL OR status_aplicacao = '')
                AND produto IS NOT NULL
                ORDER BY data_aplicacao DESC
            """, get_engine())
        except Exception:
            df_pend = pd.DataFrame()

        if df_pend.empty:
            st.success("✅ Nenhuma aplicação pendente de confirmação!")
        else:
            st.info(f"📋 {len(df_pend)} aplicação(ões) aguardando confirmação de que foi aplicado ao animal.")

            _nome_conf = st.session_state.get("usuario", {}).get("nome", "")
            confirmado_por = st.text_input("Seu nome (quem está confirmando)", value=_nome_conf)

            for _, row in df_pend.iterrows():
                rid = str(row["id"])
                cor_status = "#e8b84b"

                st.markdown(f"""
<div style='background:var(--surface);border:1px solid rgba(232,184,75,0.3);
border-left:4px solid {cor_status};border-radius:0 10px 10px 0;
padding:12px 16px;margin-bottom:8px'>
  <div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px'>
    <div>
      <div style='font-weight:500;color:var(--text);font-size:0.92rem'>
        🐎 {row.get("animal","")} — {row.get("procedimento","")}
      </div>
      <div style='font-size:0.78rem;color:var(--muted);margin-top:3px'>
        💊 {row.get("produto","")} &nbsp;·&nbsp;
        📦 {row.get("quantidade_usada","")} {row.get("unidade","")} &nbsp;·&nbsp;
        📅 {row.get("data_aplicacao","")} &nbsp;·&nbsp;
        👤 {row.get("responsavel","")}
      </div>
    </div>
    <span style='font-size:0.7rem;background:rgba(232,184,75,0.15);color:#e8b84b;
    border:1px solid rgba(232,184,75,0.3);border-radius:99px;padding:2px 10px'>
      Aguardando confirmação
    </span>
  </div>
</div>
""", unsafe_allow_html=True)

                col_c1, col_c2, col_c3 = st.columns([2, 1, 1])
                with col_c2:
                    if st.button("✅ Confirmar aplicação", key=f"conf_san_{rid}", use_container_width=True):
                        # Baixa o estoque AGORA
                        qtd = float(row.get("quantidade_usada") or 0)
                        produto_nome = str(row.get("produto", ""))
                        ok, nova_qtd, preco_u, erro = baixar_estoque(produto_nome, qtd)

                        if not ok:
                            st.error(f"⚠️ {erro} — Aplicação confirmada mas estoque não alterado.")
                        else:
                            st.success(f"✅ Estoque de '{produto_nome}' atualizado: {nova_qtd:.1f} restantes.")

                        c.execute("""
                            UPDATE sanitario
                            SET status_aplicacao = %s, data_confirmacao = %s, confirmado_por = %s
                            WHERE id = %s
                        """, ("Aplicado", datetime.now().strftime("%d/%m/%Y %H:%M"),
                              confirmado_por, rid))
                        conn.commit()
                        listar_farmacia.clear()
                        registrar_auditoria("Sanitário", "Confirmação de aplicação", f"Aplicação confirmada: {row.get("produto","")} em {row.get("animal","")}")
                        st.rerun()

                with col_c3:
                    if st.button("❌ Cancelar", key=f"canc_san_{rid}", use_container_width=True):
                        c.execute("""
                            UPDATE sanitario SET status_aplicacao = %s WHERE id = %s
                        """, ("Cancelado", rid))
                        conn.commit()
                        st.rerun()

    elif aba == "Alertas Sanitários":
        df = pd.read_sql_query("SELECT * FROM sanitario WHERE animal IS NOT NULL", get_engine())

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
        df = pd.read_sql_query("SELECT * FROM sanitario WHERE animal IS NOT NULL", get_engine())

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
    titulo_pagina("🔎 Consulta ABQM", "Integração assistida, preenchimento por IA e árvore genealógica")

    aba = st.radio(
        "Opção",
        ["🌐 Consultar ABQM", "🤖 Preencher por IA", "🌳 Árvore Genealógica", "📋 Histórico ABQM"],
        horizontal=True
    )

    animais_abqm = listar_animais()

    # ── CONSULTAR ABQM ──────────────────────────────────────
    if aba == "🌐 Consultar ABQM":
        titulo_pagina("🌐 Consulta Oficial ABQM", "Busque o animal no site oficial e salve os dados aqui")

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            registro_busca = st.text_input("Nº de Registro ABQM", placeholder="Ex: 000123456")
        with col_b2:
            nome_busca = st.text_input("Nome do animal", placeholder="Ex: TROVÃO DO RECANTO")

        col_link1, col_link2, col_link3 = st.columns(3)
        with col_link1:
            url_reg = f"https://consulta.abqm.com.br/animal/{registro_busca}" if registro_busca else "https://consulta.abqm.com.br/"
            st.link_button("🔎 Buscar por Registro", url_reg, use_container_width=True)
        with col_link2:
            url_nome = f"https://consulta.abqm.com.br/?nome={nome_busca.replace(' ', '+')}" if nome_busca else "https://consulta.abqm.com.br/"
            st.link_button("🔎 Buscar por Nome", url_nome, use_container_width=True)
        with col_link3:
            st.link_button("🏠 Site ABQM", "https://www.abqm.com.br", use_container_width=True)

        st.markdown("---")
        st.info("💡 **Como usar:** Abra a consulta ABQM acima, encontre o animal, copie os dados e use a aba **🤖 Preencher por IA** para preencher tudo automaticamente.")

        st.markdown("### Salvar dados manualmente")

        if animais_abqm.empty:
            st.warning("Cadastre um animal primeiro.")
        else:
            animais_abqm["descricao"] = animais_abqm["nome"] + " - " + animais_abqm["tipo"]
            escolha = st.selectbox("Vincular ao animal", animais_abqm["descricao"].tolist())
            animal_nome = escolha.split(" - ")[0]
            animal_atual = pd.read_sql_query(
                "SELECT * FROM animais WHERE nome = %s", get_engine(), params=(animal_nome,)
            ).iloc[0]

            col1, col2 = st.columns(2)
            with col1:
                registro_abqm  = st.text_input("Registro ABQM", value=str(animal_atual.get("registro_abqm", "") or registro_busca or ""))
                nome_oficial   = st.text_input("Nome oficial", value=str(animal_atual.get("nome_oficial_abqm", "") or animal_nome))
                pai            = st.text_input("Pai", value=str(animal_atual.get("pai_abqm", "") or ""))
                reg_pai        = st.text_input("Registro do Pai", value=str(animal_atual.get("reg_pai_abqm", "") or ""))
                mae            = st.text_input("Mãe", value=str(animal_atual.get("mae_abqm", "") or ""))
                reg_mae        = st.text_input("Registro da Mãe", value=str(animal_atual.get("reg_mae_abqm", "") or ""))
                pelagem        = st.text_input("Pelagem", value=str(animal_atual.get("pelagem_abqm", "") or animal_atual.get("cor", "") or ""))
                modalidade     = st.text_input("Modalidade", value=str(animal_atual.get("modalidade_abqm", "") or ""))
            with col2:
                avo_pat        = st.text_input("Avô Paterno", value=str(animal_atual.get("avo_pat_abqm", "") or ""))
                avo_pat_reg    = st.text_input("Reg. Avô Paterno", value=str(animal_atual.get("avo_pat_reg", "") or ""))
                avo_mat        = st.text_input("Avó Materna", value=str(animal_atual.get("avo_mat_abqm", "") or ""))
                avo_mat_reg    = st.text_input("Reg. Avó Materna", value=str(animal_atual.get("avo_mat_reg", "") or ""))
                nascimento     = st.text_input("Nascimento", value=str(animal_atual.get("nascimento", "") or ""))
                criador        = st.text_input("Criador", value=str(animal_atual.get("criador_abqm", "") or ""))
                proprietario   = st.text_input("Proprietário", value=str(animal_atual.get("proprietario_abqm", "") or ""))
                observacoes    = st.text_area("Observações", value=str(animal_atual.get("obs_abqm", "") or ""))

            if st.button("💾 Salvar dados ABQM", use_container_width=True):
                c.execute("""
                    UPDATE animais
                    SET registro_abqm=%s, nome_oficial_abqm=%s, pai_abqm=%s, mae_abqm=%s,
                        criador_abqm=%s, proprietario_abqm=%s, obs_abqm=%s,
                        reg_pai_abqm=%s, reg_mae_abqm=%s, pelagem_abqm=%s, modalidade_abqm=%s,
                        avo_pat_abqm=%s, avo_pat_reg=%s, avo_mat_abqm=%s, avo_mat_reg=%s
                    WHERE nome = %s
                """, (
                    registro_abqm, nome_oficial, pai, mae, criador, proprietario, observacoes,
                    reg_pai, reg_mae, pelagem, modalidade,
                    avo_pat, avo_pat_reg, avo_mat, avo_mat_reg,
                    animal_nome
                ))
                c.execute("""
                    INSERT INTO abqm_consultas
                    (animal, registro_abqm, nome_oficial, pai, mae, pelagem,
                     nascimento, criador, proprietario, observacoes, data_cadastro)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    animal_nome, registro_abqm, nome_oficial, pai, mae, pelagem,
                    nascimento, criador, proprietario, observacoes,
                    datetime.now().strftime("%d/%m/%Y %H:%M")
                ))
                conn.commit()
                listar_animais.clear()
                st.success("✅ Dados ABQM salvos com sucesso!")

    # ── PREENCHER POR IA ────────────────────────────────────
    elif aba == "🤖 Preencher por IA":
        titulo_pagina("📄 Importar PDF / Texto ABQM", "Faça upload do PDF ou cole o texto da ficha ABQM")

        st.markdown("""
<div style="background:#0d1f3c;border:1px solid rgba(212,175,80,0.2);border-radius:12px;padding:16px;margin-bottom:16px">
  <div style="font-size:0.88rem;color:#d4c9b0;font-weight:500;margin-bottom:8px">📋 Como usar:</div>
  <div style="font-size:0.82rem;color:#7a8fa3;line-height:1.9">
    <strong style="color:#d4af50">Opção 1 — PDF:</strong> Salve a ficha do animal da ABQM como PDF e faça upload abaixo<br>
    <strong style="color:#d4af50">Opção 2 — Texto:</strong> Acesse <strong style="color:#d4af50">consulta.abqm.com.br</strong>, selecione todo o texto (Ctrl+A), copie (Ctrl+C) e cole abaixo<br>
    O sistema extrai automaticamente: nome, registro, pai, mãe, avós, pelagem, criador e proprietário
  </div>
</div>
""", unsafe_allow_html=True)

        animais_abqm["descricao"] = animais_abqm["nome"] + " - " + animais_abqm["tipo"] if not animais_abqm.empty else None

        opcoes_animal = ["➕ Cadastrar como novo animal"] + (animais_abqm["descricao"].tolist() if not animais_abqm.empty else [])
        escolha_ia = st.selectbox(
            "O que fazer com os dados extraídos?",
            opcoes_animal,
            key="ia_animal",
            help="Escolha 'Cadastrar como novo animal' para criar um novo cadastro, ou selecione um animal existente para atualizar seus dados ABQM."
        )
        animal_ia = None if escolha_ia == "➕ Cadastrar como novo animal" else escolha_ia.split(" - ")[0]

        if animal_ia is None:
            st.info("📋 Após extrair os dados do PDF, um formulário de cadastro completo será aberto.")
        else:
            st.info(f"📝 Os dados ABQM serão salvos no animal: **{animal_ia}**")

        modo = st.radio("Modo de entrada", ["📄 Upload de PDF", "📋 Colar texto"], horizontal=True)
        texto_extraido = ""

        if modo == "📄 Upload de PDF":
            pdf_file = st.file_uploader("Faça upload do PDF da ficha ABQM", type=["pdf"])
            if pdf_file:
                try:
                    import io as _io
                    pdf_bytes = pdf_file.read()
                    try:
                        from pdfminer.high_level import extract_text as _pdfext
                        texto_extraido = _pdfext(_io.BytesIO(pdf_bytes))
                    except ImportError:
                        try:
                            import pypdf as _pypdf
                            reader = _pypdf.PdfReader(_io.BytesIO(pdf_bytes))
                            texto_extraido = "\n".join(p.extract_text() or "" for p in reader.pages)
                        except ImportError:
                            try:
                                import PyPDF2 as _PyPDF2
                                reader = _PyPDF2.PdfReader(_io.BytesIO(pdf_bytes))
                                texto_extraido = "\n".join(p.extract_text() or "" for p in reader.pages)
                            except Exception:
                                st.error("Biblioteca de PDF não encontrada. Use a opção Colar texto.")
                    if texto_extraido:
                        st.success(f"✅ PDF lido! {len(texto_extraido)} caracteres extraídos.")
                        with st.expander("Ver texto extraído"):
                            st.text(texto_extraido[:2000])
                except Exception as e:
                    st.error(f"Erro ao ler PDF: {e}")
        else:
            texto_extraido = st.text_area(
                "Cole aqui o texto copiado da página ABQM",
                height=200,
                placeholder="Cole o texto completo da ficha do animal no site da ABQM..."
            )

        def _normalizar_pdf_abqm(texto):
            """
            Corrige texto do pypdf que separa cada letra com espaço.
            'R O A N S  O F  F L I N G' → 'ROANS OF FLING'
            Linhas normais: apenas normaliza espaços duplos.
            """
            import re as _r
            linhas_out = []
            for linha in texto.splitlines():
                l = linha.strip()
                # Detecta linha letra-por-letra: maioria dos tokens tem 1 char
                tokens = l.replace('  ', ' ').split(' ')
                qtd_isolados = sum(1 for t in tokens if len(t) == 1 and t.isalnum())
                if qtd_isolados >= 4 and qtd_isolados > len(tokens) * 0.5:
                    # Remove espaço simples entre letras/nums (espaço duplo = separador de palavra)
                    l = _r.sub(r'(?<=[A-Z0-9]) (?=[A-Z0-9])', '', l)
                    l = _r.sub(r'  +', ' ', l).strip()
                else:
                    # Apenas normaliza espaços duplos para simples
                    l = _r.sub(r'  +', ' ', l).strip()
                linhas_out.append(l)
            return "\n".join(linhas_out)

        def _extrair_dados_abqm(texto):
            import re as _re
            # Normaliza espaços espúrios do pypdf (R O A N S → ROANS)
            texto = _normalizar_pdf_abqm(texto)
            linhas = [_re.sub(r'\s+', ' ', l).strip() for l in texto.splitlines() if l.strip()]
            dados = {k: "" for k in [
                "registro_abqm","nome_oficial","pai","reg_pai","mae","reg_mae",
                "avo_paterno","reg_avo_paterno","avo_materno","reg_avo_materno",
                "bisavo_pp","bisavo_pm","bisavo_mp","bisavo_mm",
                "pelagem","nascimento","sexo","criador","proprietario","modalidade","microchip"
            ]}

            # ── Campos diretos por prefixo "Chave: Valor" ──
            kw_map = {
                "Nascimento:": "nascimento",
                "Sexo:": "sexo",
                "Pelagem:": "pelagem",
                "Proprietário:": "proprietario",
                "Criador:": "criador",
                "Chip:": "microchip",
                "Modalidade:": "modalidade",
            }
            for linha in linhas:
                for kw, campo in kw_map.items():
                    if linha.startswith(kw):
                        val = linha[len(kw):].strip()
                        if val and val != "--":
                            dados[campo] = val

            # ── Nome oficial e registro (primeira linha: NOME - PXXXXXX) ──
            # Normaliza espaços múltiplos antes de tentar extrair
            linhas_norm = [_re.sub(r'\s+', ' ', l).strip() for l in linhas]

            for linha in linhas_norm[:8]:
                # Padrão: "NOME DO ANIMAL - P367119" ou "NOME - 1234567"
                m = _re.match(r'^(.+?)\s*[-–]\s*([P]?\d{4,})\s*$', linha)
                if m:
                    dados["nome_oficial"] = m.group(1).strip()
                    dados["registro_abqm"] = m.group(2).strip()
                    break

            # Usa linhas normalizadas daqui em diante também
            linhas = linhas_norm

            # ── Filiação: PAI x MÃE REGISTRO ──
            for linha in linhas:
                if linha.startswith("Filiação:"):
                    fil = linha.replace("Filiação:", "").strip()
                    fil = _re.sub(r'\s+', ' ', fil)  # normaliza espaços
                    # Divide em pai e mãe pelo " x " ou " X "
                    partes = _re.split(r'\s+[xX]\s+', fil, maxsplit=1)
                    if len(partes) == 2:
                        dados["pai"] = _re.sub(r'\s+', ' ', partes[0].strip())
                        # Mãe pode ter registro no final: "NOME PXXXXXX"
                        mae_m = _re.match(r'^(.+?)\s+([P]?\d{4,})\s*$', partes[1].strip())
                        if mae_m:
                            dados["mae"] = _re.sub(r'\s+', ' ', mae_m.group(1).strip())
                            dados["reg_mae"] = mae_m.group(2).strip()
                        else:
                            dados["mae"] = _re.sub(r'\s+', ' ', partes[1].strip())
                    break

            # ── Árvore genealógica — bloco após "MARCAS E SINAIS" ──
            # Formato ABQM: pares alternados de NOME / REGISTRO [Pelagem]
            # Ordem posicional confirmada:
            # [0]=PAI  [1]=MÃE
            # [2]=AvôPat  [3]=AvóPat  [4]=AvôMat  [5]=AvóMat
            # [6]=BisavôPP [7]=BisavôPM [8]=BisavôMP [9]=BisavôMM
            idx_marcas = None
            for i, l in enumerate(linhas):
                if "MARCAS E SINAIS" in l.upper():
                    idx_marcas = i
                    break

            inicio_arvore = None
            if idx_marcas is not None:
                for i in range(idx_marcas + 1, min(idx_marcas + 6, len(linhas))):
                    if _re.match(r'^[A-ZÁÉÍÓÚÀÂÊÔÃÕÇÜÑ\s\'\(\)\.]+$', linhas[i]) and len(linhas[i]) > 3:
                        inicio_arvore = i
                        break
            else:
                # Fallback: procura bloco após última linha de dados
                for i, l in enumerate(linhas):
                    if l.startswith("Cert. de Reg") or l.startswith("Pontos:"):
                        inicio_arvore = i + 1
                        break

            if inicio_arvore is not None:
                arvore = linhas[inicio_arvore:]
                pares = []
                i = 0
                while i < len(arvore):
                    l = arvore[i]
                    # Nome: apenas letras maiúsculas, espaços, apóstrofos, parênteses
                    if _re.match(r'^[A-ZÁÉÍÓÚÀÂÊÔÃÕÇÜÑ\s\'\(\)\.]+$', l) and len(l) > 2 and not l.startswith("MARCAS"):
                        nome = l.strip()
                        reg = ""
                        if i + 1 < len(arvore):
                            prox = arvore[i + 1]
                            m = _re.match(r'^([P]?\d+)\s*(.*)$', prox)
                            if m:
                                reg = m.group(1)
                                i += 2
                            else:
                                i += 1
                        else:
                            i += 1
                        pares.append((_re.sub(r"\s+", " ", nome).strip(), reg))
                    else:
                        i += 1

                # Mapeamento posicional correto (verificado com PDF real da ABQM)
                mapa_pos = [
                    ("pai", "reg_pai"),               # [0]
                    ("mae", "reg_mae"),                # [1]
                    ("avo_paterno", "reg_avo_paterno"),# [2]
                    ("avo_materno", "reg_avo_materno"),# [3] — avó pat (mãe do pai)
                    (None, None),                      # [4] — avô mat (pai da mãe) ignorado
                    (None, None),                      # [5] — avó mat (mãe da mãe)
                    ("bisavo_pp", None),               # [6]
                    ("bisavo_pm", None),               # [7]
                    ("bisavo_mp", None),               # [8]
                    ("bisavo_mm", None),               # [9]
                ]
                for idx, (nome_campo, reg_campo) in enumerate(mapa_pos):
                    if idx < len(pares):
                        n, r = pares[idx]
                        if nome_campo and not dados.get(nome_campo):
                            dados[nome_campo] = n
                        if reg_campo and not dados.get(reg_campo):
                            dados[reg_campo] = r

                # Avô e avó maternos nas posições 4 e 5
                if len(pares) > 4 and not dados["avo_materno"]:
                    dados["avo_materno"] = pares[4][0]
                    dados["reg_avo_materno"] = pares[4][1]

            return dados

        if texto_extraido and st.button("🔍 Extrair dados automaticamente", use_container_width=True):
            with st.spinner("Analisando ficha ABQM..."):
                dados = _extrair_dados_abqm(texto_extraido)
                st.session_state["abqm_ia_dados"] = dados
                st.session_state["abqm_ia_animal"] = animal_ia
                preenchidos = sum(1 for v in dados.values() if v)
                st.success(f"✅ {preenchidos} campos identificados! Revise abaixo e salve.")

        if "abqm_ia_dados" in st.session_state:
            dados = st.session_state["abqm_ia_dados"]
            st.markdown("### ✏️ Revise e confirme os dados extraídos")
            col1, col2 = st.columns(2)
            with col1:
                d_registro   = st.text_input("Registro ABQM",   value=dados.get("registro_abqm",""), key="d_reg")
                d_nome       = st.text_input("Nome oficial",     value=dados.get("nome_oficial",""),  key="d_nome")
                d_pai        = st.text_input("Pai",              value=dados.get("pai",""),            key="d_pai")
                d_reg_pai    = st.text_input("Registro do Pai",  value=dados.get("reg_pai",""),        key="d_rpai")
                d_mae        = st.text_input("Mãe",              value=dados.get("mae",""),            key="d_mae")
                d_reg_mae    = st.text_input("Registro da Mãe",  value=dados.get("reg_mae",""),        key="d_rmae")
                d_pelagem    = st.text_input("Pelagem",           value=dados.get("pelagem",""),        key="d_pel")
                d_modalidade = st.text_input("Modalidade",        value=dados.get("modalidade",""),    key="d_mod")
            with col2:
                d_avo_pat    = st.text_input("Avô Paterno",      value=dados.get("avo_paterno",""),    key="d_avopat")
                d_avo_pat_r  = st.text_input("Reg. Avô Paterno", value=dados.get("reg_avo_paterno",""),key="d_avopat_r")
                d_avo_mat    = st.text_input("Avó Materna",      value=dados.get("avo_materno",""),    key="d_avomat")
                d_avo_mat_r  = st.text_input("Reg. Avó Materna", value=dados.get("reg_avo_materno",""),key="d_avomat_r")
                d_bisavo_pp  = st.text_input("Bisavô Pat-Pat",   value=dados.get("bisavo_pp",""),      key="d_bpp")
                d_bisavo_pm  = st.text_input("Bisavô Pat-Mat",   value=dados.get("bisavo_pm",""),      key="d_bpm")
                d_bisavo_mp  = st.text_input("Bisavô Mat-Pat",   value=dados.get("bisavo_mp",""),      key="d_bmp")
                d_bisavo_mm  = st.text_input("Bisavô Mat-Mat",   value=dados.get("bisavo_mm",""),      key="d_bmm")
                d_nascimento = st.text_input("Nascimento",       value=dados.get("nascimento",""),     key="d_nasc")
                d_criador    = st.text_input("Criador",          value=dados.get("criador",""),        key="d_cri")
                d_prop       = st.text_input("Proprietário",     value=dados.get("proprietario",""),   key="d_prop")
                d_microchip  = st.text_input("Microchip / Chip", value=dados.get("microchip",""),     key="d_chip")

            # ── Opção: vincular a existente OU cadastrar novo ──
            st.markdown("---")
            st.markdown("""
<div style="font-size:0.68rem;color:rgba(201,168,76,0.6);text-transform:uppercase;
letter-spacing:0.12em;margin-bottom:10px">O que deseja fazer com esses dados?</div>
""", unsafe_allow_html=True)

            acao_col1, acao_col2 = st.columns(2)

            with acao_col1:
                _tem_animal = bool(st.session_state.get("abqm_ia_animal"))
                if st.button("💾 Salvar em animal existente", use_container_width=True,
                             disabled=not _tem_animal):
                    c.execute("""
                        UPDATE animais
                        SET registro_abqm=%s, nome_oficial_abqm=%s,
                            pai_abqm=%s, reg_pai_abqm=%s, mae_abqm=%s, reg_mae_abqm=%s,
                            pelagem_abqm=%s, modalidade_abqm=%s,
                            avo_pat_abqm=%s, avo_pat_reg=%s,
                            avo_mat_abqm=%s, avo_mat_reg=%s,
                            bisavo_pp_abqm=%s, bisavo_pm_abqm=%s,
                            bisavo_mp_abqm=%s, bisavo_mm_abqm=%s,
                            criador_abqm=%s, proprietario_abqm=%s
                        WHERE nome = %s
                    """, (
                        d_registro, d_nome, d_pai, d_reg_pai, d_mae, d_reg_mae,
                        d_pelagem, d_modalidade, d_avo_pat, d_avo_pat_r,
                        d_avo_mat, d_avo_mat_r, d_bisavo_pp, d_bisavo_pm,
                        d_bisavo_mp, d_bisavo_mm, d_criador, d_prop,
                        st.session_state["abqm_ia_animal"]
                    ))
                    c.execute("""
                        INSERT INTO abqm_consultas
                        (animal, registro_abqm, nome_oficial, pai, mae, pelagem,
                         nascimento, criador, proprietario, observacoes, data_cadastro)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (
                        st.session_state["abqm_ia_animal"],
                        d_registro, d_nome, d_pai, d_mae, d_pelagem,
                        d_nascimento, d_criador, d_prop,
                        "Extraído via PDF/Texto",
                        datetime.now().strftime("%d/%m/%Y %H:%M")
                    ))
                    conn.commit()
                    listar_animais.clear()
                    del st.session_state["abqm_ia_dados"]
                    st.success(f"✅ Dados ABQM salvos em '{st.session_state.get('abqm_ia_animal')}'!")
                    st.rerun()

            with acao_col2:
                if st.button("🐎 Cadastrar como novo animal", use_container_width=True):
                    st.session_state["abqm_novo_animal"] = True

            # Se escolheu "Novo animal" no seletor, abre o form automaticamente
            if animal_ia is None and not st.session_state.get("abqm_novo_animal"):
                st.session_state["abqm_novo_animal"] = True

            # ── Formulário de cadastro novo animal ──────────
            if st.session_state.get("abqm_novo_animal"):
                st.markdown("""
<div style="background:#0d1f3c;border:1px solid rgba(212,175,80,0.2);border-radius:12px;
padding:16px;margin-top:12px">
<div style="font-family:'Playfair Display',serif;font-size:1rem;color:#d4af50;margin-bottom:14px">
🐎 Cadastrar novo animal com dados ABQM
</div>
""", unsafe_allow_html=True)

                na_col1, na_col2 = st.columns(2)
                with na_col1:
                    na_nome     = st.text_input("Nome do animal *", value=d_nome, key="na_nome")
                    na_tipo     = st.selectbox("Tipo *", ["Equino", "Bovino", "Caprino", "Ovino", "Canino", "Felino", "Outro"], key="na_tipo")
                    na_raca     = st.text_input("Raça", value="Quarto de Milha", key="na_raca")
                    na_sexo     = st.selectbox("Sexo", ["Macho", "Fêmea"], key="na_sexo")
                    na_nasc     = st.text_input("Nascimento", value=d_nascimento, key="na_nasc")
                    na_pelagem  = st.text_input("Pelagem / Cor", value=d_pelagem, key="na_pelagem")
                with na_col2:
                    na_resp     = st.text_input("Responsável", key="na_resp")
                    na_tel      = st.text_input("Telefone", key="na_tel")
                    na_local    = st.text_input("Local / Pasto", key="na_local")
                    na_microchip= st.text_input("Microchip", value=dados.get("microchip", ""), key="na_microchip")
                    na_status   = st.selectbox("Status", ["Ativo", "Vendido", "Falecido", "Emprestado"], key="na_status")
                    na_obs      = st.text_area("Observações", key="na_obs")

                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("✅ Confirmar cadastro", use_container_width=True):
                        if not na_nome:
                            st.error("Informe o nome do animal.")
                        else:
                            # Verifica se já existe
                            existe = pd.read_sql_query(
                                "SELECT id FROM animais WHERE nome = %s",
                                get_engine(), params=(na_nome,)
                            )
                            if not existe.empty:
                                st.warning(f"Já existe um animal com o nome '{na_nome}'. Escolha outro nome ou use 'Salvar em animal existente'.")
                            else:
                                c.execute("""
                                    INSERT INTO animais
                                    (nome, tipo, raca, sexo, nascimento, cor,
                                     responsavel, telefone, local, microchip, status,
                                     registro_abqm, nome_oficial_abqm,
                                     pai_abqm, reg_pai_abqm, mae_abqm, reg_mae_abqm,
                                     pelagem_abqm, modalidade_abqm,
                                     avo_pat_abqm, avo_pat_reg,
                                     avo_mat_abqm, avo_mat_reg,
                                     bisavo_pp_abqm, bisavo_pm_abqm,
                                     bisavo_mp_abqm, bisavo_mm_abqm,
                                     criador_abqm, proprietario_abqm, obs)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                            %s,%s,%s,%s,%s,%s,%s,%s)
                                """, (
                                    na_nome, na_tipo, na_raca, na_sexo, na_nasc, na_pelagem,
                                    na_resp, na_tel, na_local, na_microchip, na_status,
                                    d_registro, d_nome,
                                    d_pai, d_reg_pai, d_mae, d_reg_mae,
                                    d_pelagem, d_modalidade,
                                    d_avo_pat, d_avo_pat_r,
                                    d_avo_mat, d_avo_mat_r,
                                    d_bisavo_pp, d_bisavo_pm,
                                    d_bisavo_mp, d_bisavo_mm,
                                    d_criador, d_prop, na_obs
                                ))
                                c.execute("""
                                    INSERT INTO abqm_consultas
                                    (animal, registro_abqm, nome_oficial, pai, mae,
                                     pelagem, nascimento, criador, proprietario,
                                     observacoes, data_cadastro)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                """, (
                                    na_nome, d_registro, d_nome, d_pai, d_mae,
                                    d_pelagem, d_nascimento, d_criador, d_prop,
                                    "Cadastrado via PDF/Texto ABQM",
                                    datetime.now().strftime("%d/%m/%Y %H:%M")
                                ))
                                conn.commit()
                                listar_animais.clear()
                                _carregar_dashboard.clear()
                                del st.session_state["abqm_ia_dados"]
                                st.session_state.pop("abqm_novo_animal", None)
                                st.success(f"✅ Animal '{na_nome}' cadastrado com todos os dados ABQM e genealogia!")
                                st.balloons()
                                st.rerun()

                with btn_col2:
                    if st.button("❌ Cancelar", use_container_width=True):
                        st.session_state.pop("abqm_novo_animal", None)
                        st.rerun()

                st.markdown("</div>", unsafe_allow_html=True)


    # ── ÁRVORE GENEALÓGICA ─────────────────────────────────
    elif aba == "🌳 Árvore Genealógica":
        titulo_pagina("🌳 Árvore Genealógica", "Visualização da linhagem do animal")
    elif aba == "🌳 Árvore Genealógica":
        titulo_pagina("🌳 Árvore Genealógica", "Visualização da linhagem do animal")

        if animais_abqm.empty:
            st.warning("Nenhum animal cadastrado.")
        else:
            animais_abqm["descricao"] = animais_abqm["nome"] + " - " + animais_abqm["tipo"]
            escolha_arv = st.selectbox("Selecione o animal", animais_abqm["descricao"].tolist(), key="arv_animal")
            animal_arv = escolha_arv.split(" - ")[0]

            a = pd.read_sql_query(
                "SELECT * FROM animais WHERE nome = %s", get_engine(), params=(animal_arv,)
            ).iloc[0]

            # Dados
            nome_a     = str(a.get("nome_oficial_abqm") or a.get("nome") or animal_arv)
            reg_a      = str(a.get("registro_abqm") or "")
            pai_a      = str(a.get("pai_abqm") or "")
            reg_pai    = str(a.get("reg_pai_abqm") or "")
            mae_a      = str(a.get("mae_abqm") or "")
            reg_mae    = str(a.get("reg_mae_abqm") or "")
            avo_pat    = str(a.get("avo_pat_abqm") or "")
            avo_pat_r  = str(a.get("avo_pat_reg") or "")
            avo_mat    = str(a.get("avo_mat_abqm") or "")
            avo_mat_r  = str(a.get("avo_mat_reg") or "")
            bpp        = str(a.get("bisavo_pp_abqm") or "")
            bpm        = str(a.get("bisavo_pm_abqm") or "")
            bmp        = str(a.get("bisavo_mp_abqm") or "")
            bmm        = str(a.get("bisavo_mm_abqm") or "")
            pelagem    = str(a.get("pelagem_abqm") or a.get("cor") or "")
            criador    = str(a.get("criador_abqm") or "")
            prop       = str(a.get("proprietario_abqm") or "")
            nasc       = str(a.get("nascimento") or "")

            def _no(nome, reg="", cor="#0d1f3c", borda="#d4af50", texto="#e8e2d5"):
                reg_txt = f"<div style='font-size:0.6rem;color:#7a8fa3;margin-top:1px'>{reg}</div>" if reg else ""
                sem_dado = not nome or nome in ("", "None")
                bg = "rgba(13,31,60,0.4)" if sem_dado else cor
                op = "0.45" if sem_dado else "1"
                label = "—" if sem_dado else nome[:28]
                return f"""<div style='background:{bg};border:1px solid {borda};border-radius:8px;
padding:7px 10px;text-align:center;opacity:{op};min-width:130px;max-width:160px'>
<div style='font-size:0.75rem;font-weight:500;color:{texto};line-height:1.3'>{label}</div>
{reg_txt}</div>"""

            html_arv = f"""
<style>
.arv-wrap{{font-family:'DM Sans',sans-serif;overflow-x:auto;padding:10px 0}}
.arv-row{{display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:6px}}
.arv-col{{display:flex;flex-direction:column;gap:6px;align-items:center}}
.arv-linha{{color:rgba(212,175,80,0.25);font-size:1.2rem;line-height:1}}
.arv-titulo{{font-family:'Playfair Display',serif;font-size:0.7rem;color:rgba(212,175,80,0.45);
text-transform:uppercase;letter-spacing:0.12em;text-align:center;margin-bottom:4px}}
</style>
<div class="arv-wrap">

  <div class="arv-titulo">Árvore Genealógica — {nome_a}</div>

  <!-- Cabeçalho de geração -->
  <div style="display:flex;justify-content:center;gap:80px;margin-bottom:2px">
    <div style="font-size:0.62rem;color:rgba(212,175,80,0.35);text-transform:uppercase;letter-spacing:0.1em">Animal</div>
    <div style="font-size:0.62rem;color:rgba(212,175,80,0.35);text-transform:uppercase;letter-spacing:0.1em">Pais</div>
    <div style="font-size:0.62rem;color:rgba(212,175,80,0.35);text-transform:uppercase;letter-spacing:0.1em">Avós</div>
    <div style="font-size:0.62rem;color:rgba(212,175,80,0.35);text-transform:uppercase;letter-spacing:0.1em">Bisavós</div>
  </div>

  <div style="display:flex;align-items:center;gap:16px;justify-content:center">

    <!-- Animal principal -->
    <div style="display:flex;flex-direction:column;align-items:center">
      {_no(nome_a, reg_a, "#0f2444", "#d4af50", "#d4af50")}
      <div style="font-size:0.62rem;color:#5a7a6a;margin-top:4px">{pelagem}</div>
      <div style="font-size:0.62rem;color:#5a7a6a">{nasc}</div>
    </div>

    <div style="color:rgba(212,175,80,0.2);font-size:1.5rem">›</div>

    <!-- Pais -->
    <div style="display:flex;flex-direction:column;gap:24px;align-items:center">
      <div>
        <div style="font-size:0.62rem;color:#4a9e6b;text-align:center;margin-bottom:3px;letter-spacing:0.06em">PAI</div>
        {_no(pai_a, reg_pai, "#0d1f3c", "#4a9e6b")}
      </div>
      <div>
        <div style="font-size:0.62rem;color:#4a8fcf;text-align:center;margin-bottom:3px;letter-spacing:0.06em">MÃE</div>
        {_no(mae_a, reg_mae, "#0d1f3c", "#4a8fcf")}
      </div>
    </div>

    <div style="color:rgba(212,175,80,0.2);font-size:1.5rem">›</div>

    <!-- Avós -->
    <div style="display:flex;flex-direction:column;gap:12px;align-items:center">
      <div>
        <div style="font-size:0.6rem;color:#4a9e6b;text-align:center;margin-bottom:2px">AVÔ PAT.</div>
        {_no(avo_pat, avo_pat_r, "#0d1f3c", "#4a9e6b")}
      </div>
      <div style="height:12px"></div>
      <div>
        <div style="font-size:0.6rem;color:#4a8fcf;text-align:center;margin-bottom:2px">AVÓ MAT.</div>
        {_no(avo_mat, avo_mat_r, "#0d1f3c", "#4a8fcf")}
      </div>
    </div>

    <div style="color:rgba(212,175,80,0.2);font-size:1.5rem">›</div>

    <!-- Bisavós -->
    <div style="display:flex;flex-direction:column;gap:6px;align-items:center">
      <div>
        <div style="font-size:0.58rem;color:#5a7a6a;text-align:center;margin-bottom:2px">BISAVÔ P-P</div>
        {_no(bpp, "", "#0a1628", "#3a5068", "#8a9bb0")}
      </div>
      <div>
        <div style="font-size:0.58rem;color:#5a7a6a;text-align:center;margin-bottom:2px">BISAVÔ P-M</div>
        {_no(bpm, "", "#0a1628", "#3a5068", "#8a9bb0")}
      </div>
      <div>
        <div style="font-size:0.58rem;color:#5a7a6a;text-align:center;margin-bottom:2px">BISAVÔ M-P</div>
        {_no(bmp, "", "#0a1628", "#3a5068", "#8a9bb0")}
      </div>
      <div>
        <div style="font-size:0.58rem;color:#5a7a6a;text-align:center;margin-bottom:2px">BISAVÔ M-M</div>
        {_no(bmm, "", "#0a1628", "#3a5068", "#8a9bb0")}
      </div>
    </div>

  </div>

  <!-- Rodapé informativo -->
  <div style="margin-top:16px;display:flex;gap:16px;justify-content:center;flex-wrap:wrap">
    <div style="font-size:0.72rem;color:#5a7a6a">🧑‍🌾 Criador: <span style="color:#d4c9b0">{criador or '—'}</span></div>
    <div style="font-size:0.72rem;color:#5a7a6a">🏠 Proprietário: <span style="color:#d4c9b0">{prop or '—'}</span></div>
    <div style="font-size:0.72rem;color:#5a7a6a">🎨 Pelagem: <span style="color:#d4c9b0">{pelagem or '—'}</span></div>
  </div>
</div>
"""
            st.markdown(html_arv, unsafe_allow_html=True)

            # Legenda de completude
            campos_genealogia = [pai_a, mae_a, avo_pat, avo_mat, bpp, bpm, bmp, bmm]
            preenchidos = sum(1 for c0 in campos_genealogia if c0 and c0 != "None")
            pct = int(preenchidos / len(campos_genealogia) * 100)

            st.markdown(f"""
<div style="background:#0d1f3c;border:1px solid rgba(212,175,80,0.12);border-radius:10px;
padding:12px 16px;margin-top:12px;display:flex;align-items:center;gap:12px">
  <div style="flex:1">
    <div style="font-size:0.72rem;color:#5a7a6a;margin-bottom:6px">Completude da genealogia</div>
    <div style="background:#0a1628;border-radius:99px;height:6px;overflow:hidden">
      <div style="background:{'#4a9e6b' if pct>=75 else '#e8b84b' if pct>=40 else '#e05252'};
        width:{pct}%;height:100%;border-radius:99px;transition:width .3s"></div>
    </div>
  </div>
  <div style="font-family:'Playfair Display',serif;font-size:1.2rem;
    color:{'#4a9e6b' if pct>=75 else '#e8b84b' if pct>=40 else '#e05252'}">{pct}%</div>
</div>
""", unsafe_allow_html=True)

            if pct < 100:
                st.info("💡 Para completar a árvore, use a aba **🤖 Preencher por IA** colando o texto do site da ABQM.")

            # Exportar PDF da árvore
            if st.button("📄 Gerar PDF da Árvore Genealógica", use_container_width=True):
                _init_fonte_pdf()
                buf = BytesIO()
                pdf = canvas.Canvas(buf, pagesize=letter)
                larg, alt = letter

                if os.path.exists(LOGO):
                    pdf.drawImage(LOGO, 130, 690, width=350, height=95, preserveAspectRatio=True, mask="auto")

                pdf.setFont(_fonte(bold=True), 14)
                pdf.drawCentredString(larg/2, 660, _pdf_str(f"ÁRVORE GENEALÓGICA — {nome_a}"))
                pdf.setFont(_fonte(), 9)
                pdf.drawCentredString(larg/2, 645, _pdf_str(f"Registro ABQM: {reg_a}  |  Pelagem: {pelagem}  |  Nascimento: {nasc}"))

                y = 610
                secoes_pdf = [
                    ("ANIMAL",   [(nome_a, reg_a)]),
                    ("PAI",      [(pai_a, reg_pai)]),
                    ("MÃE",      [(mae_a, reg_mae)]),
                    ("AVÔ PATERNO", [(avo_pat, avo_pat_r)]),
                    ("AVÓ MATERNA", [(avo_mat, avo_mat_r)]),
                    ("BISAVÓS",  [(bpp, "Pat-Pat"), (bpm, "Pat-Mat"), (bmp, "Mat-Pat"), (bmm, "Mat-Mat")]),
                    ("CRIADOR / PROPRIETÁRIO", [(criador, "Criador"), (prop, "Proprietário")]),
                ]
                for titulo_pdf, items in secoes_pdf:
                    pdf.setFont(_fonte(bold=True), 10)
                    pdf.drawString(50, y, _pdf_str(titulo_pdf))
                    y -= 14
                    pdf.setFont(_fonte(), 9)
                    for nome_item, detalhe in items:
                        if nome_item and nome_item != "None":
                            pdf.drawString(70, y, _pdf_str(f"{detalhe}: {nome_item}" if detalhe else nome_item))
                            y -= 12
                    y -= 4
                    if y < 80:
                        pdf.showPage(); y = 750

                pdf.save()
                st.download_button(
                    "📥 Baixar PDF",
                    data=buf.getvalue(),
                    file_name=f"genealogia_{animal_arv}.pdf",
                    mime="application/pdf"
                )

    # ── HISTÓRICO ABQM ─────────────────────────────────────
    elif aba == "📋 Histórico ABQM":
        df = pd.read_sql_query("SELECT * FROM abqm_consultas WHERE animal IS NOT NULL ORDER BY id DESC", get_engine())
        if not df.empty:
            st.dataframe(df, use_container_width=True, hide_index=True)
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
    titulo_pagina("📥 Importar NF-e / XML", "Importe produtos da NF-e para Farmácia ou Ração")

    st.markdown("""
<style>
[data-testid="stFileUploaderDropzoneInstructions"] span:first-child { display: none !important; }
[data-testid="stFileUploadDropzone"] button { min-width: 100px !important; }
</style>
""", unsafe_allow_html=True)

    st.markdown("**📎 Selecione o arquivo XML da NF-e**")
    arquivo_xml = st.file_uploader("XML", type=["xml"], label_visibility="collapsed")
    st.markdown("---")

    if arquivo_xml is not None:
        try:
            dados_nfe = ler_xml_nfe(arquivo_xml.read())
            produtos = dados_nfe["produtos"]

            # Cabeçalho da NF-e
            st.markdown(f"""
<div style='background:var(--surface);border:1px solid var(--line);border-radius:10px;
padding:14px 18px;margin-bottom:16px;display:flex;gap:24px;flex-wrap:wrap'>
  <div><div style='font-size:0.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em'>NF-e</div>
       <div style='font-weight:500;color:var(--text)'>{dados_nfe.get("numero_nfe","—")}</div></div>
  <div><div style='font-size:0.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em'>Fornecedor</div>
       <div style='font-weight:500;color:var(--text)'>{dados_nfe.get("fornecedor","—")}</div></div>
  <div><div style='font-size:0.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em'>Emissão</div>
       <div style='font-weight:500;color:var(--text)'>{dados_nfe.get("data_emissao","—")}</div></div>
  <div><div style='font-size:0.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em'>Produtos</div>
       <div style='font-weight:500;color:var(--text)'>{len(produtos)}</div></div>
</div>
""", unsafe_allow_html=True)

            if not produtos:
                st.warning("Nenhum produto encontrado no XML.")
            else:
                st.markdown("### Classifique cada produto e escolha o destino")
                st.caption("Para cada produto, escolha se vai para a **Farmácia** (medicamentos) ou para a **Ração** (ração, suplemento, sal mineral). Você pode desmarcar os que não quer importar.")

                # Categorias por destino
                cats_farmacia = ["Antibiótico","Anti-inflamatório","Vermífugo","Vacina","Suplemento","Curativo","Hormônio","Reprodução","Outro"]
                cats_racao    = ["Ração","Suplemento","Sal Mineral","Volumoso","Outro"]

                # Monta df editável com coluna destino
                rows = []
                for p in produtos:
                    nome = p.get("produto","")
                    # Heurística de destino pelo nome
                    nome_up = nome.upper()
                    if any(x in nome_up for x in ["RAÇAO","RACAO","RAÇÃO","FENO","SAL MIN","SUPL","PREMIX","VOLUMOSO","FARELO"]):
                        destino_auto = "🌾 Ração"
                    else:
                        destino_auto = "💊 Farmácia"
                    rows.append({
                        "importar": True,
                        "destino": destino_auto,
                        "produto": nome,
                        "quantidade": p.get("quantidade","1"),
                        "unidade": p.get("unidade","UN"),
                        "valor_unitario": p.get("valor_unitario","0"),
                        "valor_total": p.get("valor_total","0"),
                        "ncm": p.get("ncm",""),
                        "categoria": "Outro",
                    })

                df_edit = pd.DataFrame(rows)

                # Converte colunas numéricas para string para evitar conflito de tipo
                df_edit["quantidade"]     = df_edit["quantidade"].astype(str)
                df_edit["valor_unitario"] = df_edit["valor_unitario"].astype(str)
                df_edit["valor_total"]    = df_edit["valor_total"].astype(str)

                df_editado = st.data_editor(
                    df_edit,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "importar": st.column_config.CheckboxColumn("Importar", default=True),
                        "destino": st.column_config.SelectboxColumn(
                            "Destino",
                            options=["💊 Farmácia", "🌾 Ração"],
                            required=True
                        ),
                        "categoria": st.column_config.SelectboxColumn(
                            "Categoria",
                            options=cats_farmacia + [c for c in cats_racao if c not in cats_farmacia]
                        ),
                        "produto":        st.column_config.TextColumn("Produto"),
                        "quantidade":     st.column_config.TextColumn("Qtd"),
                        "unidade":        st.column_config.TextColumn("Un"),
                        "valor_unitario": st.column_config.TextColumn("R$ Unit."),
                        "valor_total":    st.column_config.TextColumn("R$ Total"),
                        "ncm":            st.column_config.TextColumn("NCM"),
                    }
                )

                # Separação visual
                df_farm = df_editado[df_editado["importar"] & (df_editado["destino"] == "💊 Farmácia")]
                df_rac  = df_editado[df_editado["importar"] & (df_editado["destino"] == "🌾 Ração")]

                col_r1, col_r2 = st.columns(2)
                with col_r1:
                    st.markdown(f"**💊 Farmácia:** {len(df_farm)} produto(s)")
                with col_r2:
                    st.markdown(f"**🌾 Ração:** {len(df_rac)} produto(s)")

                if st.button("📥 Importar para os estoques corretos", use_container_width=True):
                    importados_farm = 0
                    atualizados_farm = 0
                    importados_rac = 0
                    atualizados_rac = 0

                    for _, row in df_editado.iterrows():
                        if not bool(row.get("importar", False)):
                            continue

                        produto_nome = str(row["produto"]).strip()
                        if not produto_nome:
                            continue

                        quantidade   = limpar_numero(row["quantidade"])
                        valor_total  = limpar_numero(row["valor_total"])
                        valor_unit   = limpar_numero(row["valor_unitario"])
                        unidade      = str(row["unidade"])
                        categoria    = str(row["categoria"])
                        destino      = str(row["destino"])

                        # Registra na NF-e histórico
                        c.execute("""
                            INSERT INTO compras_nfe
                            (chave_nfe, numero_nfe, data_emissao, fornecedor,
                             cnpj_fornecedor, produto, ncm, quantidade, unidade,
                             valor_unitario, valor_total, data_importacao)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """, (
                            dados_nfe.get("chave_nfe",""),
                            dados_nfe.get("numero_nfe",""),
                            dados_nfe.get("data_emissao",""),
                            dados_nfe.get("fornecedor",""),
                            dados_nfe.get("cnpj_fornecedor",""),
                            produto_nome, str(row["ncm"]),
                            str(quantidade), unidade,
                            str(valor_unit), str(valor_total),
                            datetime.now().strftime("%d/%m/%Y %H:%M")
                        ))

                        # ── DESTINO: FARMÁCIA ──
                        if "Farmácia" in destino:
                            existente = pd.read_sql_query(
                                "SELECT * FROM farmacia WHERE medicamento = %s",
                                get_engine(), params=(produto_nome,)
                            )
                            volume_por_unidade, unidade_controle = extrair_volume_descricao(produto_nome)
                            unidade_controle = unidade_controle or sugerir_unidade_controle(produto_nome, unidade)
                            estoque_convertido = calcular_estoque_convertido(quantidade, volume_por_unidade)
                            preco_por_controle = calcular_preco_por_controle(valor_total, estoque_convertido)

                            if existente.empty:
                                c.execute("""
                                    INSERT INTO farmacia
                                    (medicamento, categoria, quantidade, estoque_min, unidade,
                                     preco, validade, fornecedor, obs,
                                     quantidade_compra, unidade_compra, volume_por_unidade,
                                     unidade_controle, estoque_convertido, estoque_min_controle,
                                     preco_por_controle)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                """, (
                                    produto_nome, categoria, str(quantidade), "0", unidade,
                                    str(valor_total), "", dados_nfe.get("fornecedor",""),
                                    f"NF-e {dados_nfe.get('numero_nfe','')}",
                                    str(quantidade), unidade, str(volume_por_unidade),
                                    unidade_controle, str(estoque_convertido), "0",
                                    str(preco_por_controle)
                                ))
                                importados_farm += 1
                            else:
                                qtd_atual = limpar_numero(existente.iloc[0]["quantidade"])
                                preco_atual = limpar_numero(existente.iloc[0].get("preco", 0))
                                est_conv_atual = limpar_numero(existente.iloc[0].get("estoque_convertido", 0))
                                nova_qtd = qtd_atual + quantidade
                                novo_preco = preco_atual + valor_total
                                novo_est_conv = est_conv_atual + estoque_convertido
                                novo_preco_ctrl = calcular_preco_por_controle(novo_preco, novo_est_conv)
                                c.execute("""
                                    UPDATE farmacia SET quantidade=%s, preco=%s,
                                    estoque_convertido=%s, preco_por_controle=%s,
                                    fornecedor=%s WHERE medicamento=%s
                                """, (str(nova_qtd), str(novo_preco), str(novo_est_conv),
                                      str(novo_preco_ctrl), dados_nfe.get("fornecedor",""), produto_nome))
                                atualizados_farm += 1

                        # ── DESTINO: RAÇÃO ──
                        elif "Ração" in destino:
                            preco_kg = round(valor_total / quantidade, 4) if quantidade > 0 else 0
                            existente_r = pd.read_sql_query(
                                "SELECT id, quantidade_kg FROM racao_estoque WHERE produto = %s",
                                get_engine(), params=(produto_nome,)
                            )
                            if existente_r.empty:
                                c.execute("""
                                    INSERT INTO racao_estoque
                                    (produto, categoria, quantidade_kg, unidade, data_compra,
                                     fornecedor, preco_total, preco_kg, estoque_minimo, obs)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                """, (
                                    produto_nome, categoria, str(quantidade), unidade,
                                    datetime.now().strftime("%d/%m/%Y"),
                                    dados_nfe.get("fornecedor",""),
                                    str(valor_total), str(preco_kg), "50",
                                    f"NF-e {dados_nfe.get('numero_nfe','')}"
                                ))
                                importados_rac += 1
                            else:
                                qtd_atual_r = float(existente_r.iloc[0]["quantidade_kg"] or 0)
                                c.execute(
                                    "UPDATE racao_estoque SET quantidade_kg=%s, preco_total=%s, preco_kg=%s, fornecedor=%s WHERE produto=%s",
                                    (str(qtd_atual_r + quantidade), str(valor_total),
                                     str(preco_kg), dados_nfe.get("fornecedor",""), produto_nome)
                                )
                                atualizados_rac += 1

                    conn.commit()
                    listar_farmacia.clear()
                    _carregar_estoque_racao.clear()

                    partes = []
                    if importados_farm or atualizados_farm:
                        partes.append(f"💊 Farmácia: {importados_farm} novos, {atualizados_farm} atualizados")
                    if importados_rac or atualizados_rac:
                        partes.append(f"🌾 Ração: {importados_rac} novos, {atualizados_rac} atualizados")
                    st.success("✅ Importação concluída! " + " | ".join(partes))

        except Exception as e:
            st.error(f"Não foi possível ler o XML: {e}")

    st.markdown("---")

    # ── Excluir item importado errado ────────────────────
    with st.expander("🗑️ Excluir item importado errado da Farmácia", expanded=False):
        st.caption("Use aqui para remover um produto que foi importado para a Farmácia por engano.")
        farm_atual = pd.read_sql_query(
            "SELECT id, medicamento, quantidade, fornecedor FROM farmacia WHERE medicamento IS NOT NULL ORDER BY medicamento",
            get_engine()
        )
        if not farm_atual.empty:
            opcoes_del = farm_atual["medicamento"].tolist()
            item_del = st.selectbox("Selecione o medicamento para excluir", opcoes_del, key="del_farm_nfe")
            confirmar_del = st.checkbox(f"Confirmo que desejo excluir '{item_del}' da Farmácia")
            if st.button("🗑️ Excluir da Farmácia", use_container_width=True) and confirmar_del:
                c.execute("DELETE FROM farmacia WHERE medicamento = %s", (item_del,))
                conn.commit()
                listar_farmacia.clear()
                _carregar_dashboard.clear()
                st.success(f"✅ '{item_del}' removido da Farmácia!")
                st.rerun()
        else:
            st.info("Nenhum item na Farmácia.")

    st.markdown("### Histórico de importações")
    hist = pd.read_sql_query(
        "SELECT numero_nfe, data_emissao, fornecedor, produto, quantidade, unidade, valor_total, data_importacao FROM compras_nfe WHERE produto IS NOT NULL ORDER BY id DESC LIMIT 100",
        get_engine()
    )
    if not hist.empty:
        st.dataframe(hist.rename(columns={
            "numero_nfe": "NF-e", "data_emissao": "Emissão",
            "fornecedor": "Fornecedor", "produto": "Produto",
            "quantidade": "Qtd", "unidade": "Un",
            "valor_total": "R$ Total", "data_importacao": "Importado em"
        }), use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma NF-e importada ainda.")



elif op == "Farmácia":
    titulo_pagina("💊 Farmácia", "Controle de estoque, custo e conversão para mL/L")

    atualizar_farmacia_antiga_para_controle()

    aba = st.radio(
        "Opção",
        ["Cadastrar Medicamento", "Estoque", "Alterar Medicamento", "Alertas de Estoque"],
        horizontal=True
    )

    if aba == "Cadastrar Medicamento":
        st.markdown("""
<div style='background:var(--surface);border:1px solid rgba(201,168,76,0.2);border-left:3px solid var(--gold);
border-radius:0 10px 10px 0;padding:12px 16px;margin-bottom:16px;font-size:0.85rem;color:var(--muted)'>
💡 <strong style='color:var(--text)'>Dica:</strong> Use o <strong>Princípio Ativo</strong> para agrupar produtos iguais com nomes diferentes.
Ex: "Ivermectina 1%" pode ser vendida como "IVOMEC", "IVERQUANTEL" ou "BIOMEC" — mesmo produto, fornecedores diferentes.
</div>
""", unsafe_allow_html=True)

        col1, col2 = st.columns(2)

        with col1:
            principio_ativo = st.text_input("Princípio Ativo *", placeholder="Ex: Ivermectina 1%, Penicilina G, Flunixin Meglumine")
            nome_comercial  = st.text_input("Nome Comercial / Marca", placeholder="Ex: IVOMEC, BANAMINE, PENTABIÓTICO")
            medicamento     = nome_comercial if nome_comercial else principio_ativo

            # Sugestão automática: verifica se já existe produto com mesmo princípio ativo
            if principio_ativo:
                existentes_pa = pd.read_sql_query(
                    "SELECT medicamento, fornecedor, estoque_convertido, unidade_controle FROM farmacia WHERE principio_ativo ILIKE %s",
                    get_engine(), params=(f"%{principio_ativo}%",)
                )
                if not existentes_pa.empty:
                    st.info(f"⚠️ Já existe(m) {len(existentes_pa)} produto(s) com este princípio ativo no estoque:")
                    for _, ep in existentes_pa.iterrows():
                        st.caption(f"• {ep['medicamento']} | Fornecedor: {ep.get('fornecedor','—')} | Estoque: {ep.get('estoque_convertido','?')} {ep.get('unidade_controle','')}")
                    st.caption("Você pode cadastrar mesmo assim (estoques são somados por princípio ativo no relatório).")

            categoria = st.selectbox(
                "Categoria",
                ["Antibiótico", "Anti-inflamatório", "Vermífugo", "Vacina", "Suplemento", "Curativo", "Hormônio", "Reprodução", "Soro", "Outro"]
            )
            quantidade_compra = st.number_input("Quantidade comprada", min_value=0.0, step=1.0)
            unidade_compra = st.selectbox("Unidade da compra", ["FR", "UN", "CX", "AMP", "L", "mL", "KG", "G", "SC", "Outro"])
            volume_por_unidade = st.number_input(
                "Volume por unidade",
                min_value=0.0, step=1.0,
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
                (medicamento, nome_comercial, principio_ativo, categoria,
                 quantidade, unidade, validade, fornecedor,
                 obs, estoque_min, preco, quantidade_compra, unidade_compra,
                 volume_por_unidade, unidade_controle, estoque_convertido,
                 estoque_min_controle, preco_por_controle)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                medicamento or principio_ativo, nome_comercial, principio_ativo,
                categoria, str(quantidade_compra), unidade_compra, br_data(validade),
                fornecedor, obs, str(estoque_min_controle), str(preco_total),
                str(quantidade_compra), unidade_compra, str(volume_por_unidade),
                unidade_controle, str(estoque_convertido), str(estoque_min_controle),
                str(preco_por_controle)
            ))
            conn.commit()
            listar_farmacia.clear()
            _carregar_dashboard.clear()
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

            # Conta princípios ativos únicos
            principios_unicos = df["principio_ativo"].dropna().nunique() if "principio_ativo" in df.columns else 0

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Valor total em estoque", moeda(total_estoque))
            col2.metric("Itens cadastrados", total_itens)
            col3.metric("Princípios ativos", principios_unicos)
            col4.metric("Itens em alerta", itens_baixos)

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

            # Visão agrupada por princípio ativo
            modo_view = st.radio("Visualizar por", ["📦 Produto individual", "🔬 Princípio Ativo (agrupado)"], horizontal=True)

            if modo_view == "🔬 Princípio Ativo (agrupado)" and "principio_ativo" in df.columns:
                st.markdown("### Estoque agrupado por Princípio Ativo")
                st.caption("Soma todos os produtos com mesmo princípio ativo, independente do nome comercial ou fornecedor.")

                df_grupo = df.groupby("principio_ativo").agg(
                    Produtos=("medicamento", lambda x: " / ".join(x.dropna().unique())),
                    Fornecedores=("fornecedor", lambda x: " / ".join(x.dropna().unique())),
                    Estoque_Total=("estoque_convertido_num", "sum"),
                    Unidade=("unidade_controle", "first"),
                    Valor_Total=("valor_real_estoque", "sum"),
                ).reset_index()
                df_grupo.columns = ["Princípio Ativo", "Nomes Comerciais", "Fornecedores", "Estoque Total", "Un", "Valor Total (R$)"]
                df_grupo["Valor Total (R$)"] = df_grupo["Valor Total (R$)"].apply(lambda x: f"R$ {x:,.2f}".replace(",","X").replace(".",",").replace("X","."))
                df_grupo["Estoque Total"] = df_grupo["Estoque Total"].apply(lambda x: f"{x:,.2f}".replace(",","X").replace(".",",").replace("X","."))
                st.dataframe(df_grupo, use_container_width=True, hide_index=True)

            else:
                st.markdown("### Consulta do estoque")
                busca = st.text_input("Buscar medicamento ou princípio ativo")
                df_view = df.copy()

                if busca:
                    mask = (
                        df_view["medicamento"].str.contains(busca, case=False, na=False) |
                        df_view.get("principio_ativo", pd.Series(dtype=str)).str.contains(busca, case=False, na=False) |
                        df_view.get("nome_comercial", pd.Series(dtype=str)).str.contains(busca, case=False, na=False)
                    )
                    df_view = df_view[mask]

                resumo_cols = ["id", "medicamento", "principio_ativo", "nome_comercial", "categoria",
                               "estoque_convertido", "unidade_controle", "preco_por_controle", "valor_real_estoque", "fornecedor"]
                resumo_cols = [c0 for c0 in resumo_cols if c0 in df_view.columns]
                st.dataframe(df_view[resumo_cols].rename(columns={
                    "medicamento": "Produto", "principio_ativo": "Princípio Ativo",
                    "nome_comercial": "Nome Comercial", "categoria": "Categoria",
                    "estoque_convertido": "Estoque", "unidade_controle": "Un",
                    "preco_por_controle": "R$/Un", "valor_real_estoque": "Valor Total",
                    "fornecedor": "Fornecedor"
                }), use_container_width=True, hide_index=True)

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

            med = pd.read_sql_query("SELECT * FROM farmacia WHERE id = %s", get_engine(), params=(med_id,)).iloc[0]

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
                        SET volume_por_unidade = %s, unidade_controle = %s
                        WHERE id = %s
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
                        SET medicamento = %s, categoria = %s, quantidade = %s, unidade = %s,
                            validade = %s, fornecedor = %s, obs = %s, estoque_min = %s,
                            preco = %s, quantidade_compra = %s, unidade_compra = %s,
                            volume_por_unidade = %s, unidade_controle = %s,
                            estoque_convertido = %s, estoque_min_controle = %s,
                            preco_por_controle = %s
                        WHERE id = %s
                    """, (
                        medicamento, categoria, str(quantidade_compra), unidade_compra,
                        validade, fornecedor, obs, str(estoque_min_controle),
                        str(preco_total), str(quantidade_compra), unidade_compra,
                        str(volume_por_unidade), unidade_controle,
                        str(estoque_convertido), str(estoque_min_controle),
                        str(preco_por_controle), str(med_id)
                    ))
                    conn.commit()
                    listar_farmacia.clear()
                    _carregar_dashboard.clear()
                    st.success("Medicamento alterado com sucesso!")
                    st.rerun()

            with colb2:
                confirmar = st.checkbox("Confirmar exclusão deste medicamento")
                if st.button("🗑️ Excluir Medicamento", use_container_width=True):
                    if confirmar:
                        c.execute("DELETE FROM farmacia WHERE id = %s", (med_id,))
                        conn.commit()
                        listar_farmacia.clear()
                        _carregar_dashboard.clear()
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
        ["Nova Ficha Médica", "Histórico de Fichas", "✅ Confirmar Aplicação", "Medicações Agendadas"],
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
                        "SELECT * FROM farmacia WHERE medicamento = %s", get_engine(),
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
                        f"Olá, {funcionario_nome}!\n\n"
                        f"🚨 Lembrete de medicação - Rancho Recanto Verde\n\n"
                        f"Animal: {animal_nome}\n"
                        f"Medicamento: {medicamento}\n"
                        f"Quantidade: {quantidade} {unidade}\n"
                        f"Dosagem/orientação: {dosagem}\n"
                        f"Data e hora: {data_hora_medicacao.strftime('%d/%m/%Y %H:%M')}\n\n"
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
                                "SELECT * FROM farmacia WHERE medicamento = %s", get_engine(),
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

                        c.execute("""
                            INSERT INTO fichas_medicas
                            (animal, tipo_animal, data_atendimento, motivo,
                             diagnostico, tratamento_indicado, veterinario,
                             retorno, status, custo_total, obs)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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

                        # Salva cada medicação SEM baixar estoque (aguarda confirmação de aplicação)
                        for item in st.session_state.medicacoes_ficha_temp:
                            preco_unitario_final = float(item.get("preco_unitario") or 0)
                            custo_item_final = float(item["quantidade"]) * preco_unitario_final

                            c.execute("""
                                INSERT INTO ficha_medicacoes
                                (ficha_id, animal, tipo_animal, medicamento, quantidade,
                                 unidade, dosagem, data_hora, funcionario, telefone,
                                 mensagem, status, alerta_gerado, data_alerta,
                                 preco_unitario, custo_total, obs)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        fichas = pd.read_sql_query("SELECT * FROM fichas_medicas WHERE animal IS NOT NULL ORDER BY id DESC", get_engine())

        if fichas.empty:
            st.warning("Nenhuma ficha médica registrada.")
        else:
            st.dataframe(fichas, use_container_width=True, hide_index=True)

            fichas["descricao"] = fichas["id"].astype(str) + " - " + fichas["animal"].fillna("") + " - " + fichas["data_atendimento"].fillna("")
            escolha = st.selectbox("Abrir detalhe da ficha", fichas["descricao"].tolist())
            ficha_id = escolha.split(" - ")[0]

            ficha = fichas[fichas["id"].astype(str) == ficha_id].iloc[0]
            meds = pd.read_sql_query("SELECT * FROM ficha_medicacoes WHERE ficha_id = %s ORDER BY data_hora", get_engine(), params=(ficha_id,))

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
    elif aba == "✅ Confirmar Aplicação":
        titulo_pagina("✅ Confirmar Aplicação Veterinária", "Confirme que o medicamento foi aplicado — o estoque será baixado neste momento")

        try:
            df_pend_vet = pd.read_sql_query("""
                SELECT fm.id, fm.animal, fm.medicamento, fm.quantidade, fm.unidade,
                       fm.dosagem, fm.data_hora, fm.funcionario, fm.status,
                       fic.data as data_ficha, fic.veterinario
                FROM ficha_medicacoes fm
                LEFT JOIN fichas_medicas fic ON fm.ficha_id::text = fic.id::text
                WHERE (fm.status = 'Agendada' OR fm.status IS NULL OR fm.status = '')
                AND fm.medicamento IS NOT NULL
                ORDER BY fm.data_hora DESC
            """, get_engine())
        except Exception:
            df_pend_vet = pd.DataFrame()

        if df_pend_vet.empty:
            st.success("✅ Nenhuma medicação veterinária pendente de confirmação!")
        else:
            st.info(f"💊 {len(df_pend_vet)} medicação(ões) aguardando confirmação de aplicação.")

            _nome_conf_v = st.session_state.get("usuario", {}).get("nome", "")
            confirmado_por_v = st.text_input("Seu nome (quem está confirmando)", value=_nome_conf_v, key="conf_vet_nome")

            for _, row in df_pend_vet.iterrows():
                rid = str(row["id"])
                st.markdown(f"""
<div style='background:var(--surface);border:1px solid rgba(74,143,207,0.3);
border-left:4px solid #4a8fcf;border-radius:0 10px 10px 0;
padding:12px 16px;margin-bottom:8px'>
  <div style='font-weight:500;color:var(--text);font-size:0.92rem'>
    🐎 {row.get("animal","")} — 💊 {row.get("medicamento","")}
  </div>
  <div style='font-size:0.78rem;color:var(--muted);margin-top:3px'>
    📦 {row.get("quantidade","")} {row.get("unidade","")}
    &nbsp;·&nbsp; 💉 {row.get("dosagem","")}
    &nbsp;·&nbsp; 🕐 {row.get("data_hora","")}
    &nbsp;·&nbsp; 👤 {row.get("funcionario","")}
    {'&nbsp;·&nbsp; 🩺 Dr. '+str(row.get("veterinario","")) if row.get("veterinario") else ""}
  </div>
</div>
""", unsafe_allow_html=True)

                col_c1, col_c2, col_c3 = st.columns([2, 1, 1])
                with col_c2:
                    if st.button("✅ Confirmar aplicação", key=f"conf_vet_{rid}", use_container_width=True):
                        qtd = float(row.get("quantidade") or 0)
                        med_nome = str(row.get("medicamento", ""))
                        ok, nova_qtd, preco_u, erro = baixar_estoque(med_nome, qtd)

                        if not ok:
                            st.error(f"⚠️ {erro} — Aplicação confirmada mas estoque não alterado.")
                        else:
                            st.success(f"✅ Estoque de '{med_nome}' atualizado: {nova_qtd:.1f} restantes.")

                        c.execute("""
                            UPDATE ficha_medicacoes
                            SET status = %s, data_alerta = %s
                            WHERE id = %s
                        """, ("Aplicada", datetime.now().strftime("%d/%m/%Y %H:%M"), rid))
                        conn.commit()
                        listar_farmacia.clear()
                        st.rerun()

                with col_c3:
                    if st.button("❌ Cancelar", key=f"canc_vet_{rid}", use_container_width=True):
                        c.execute("UPDATE ficha_medicacoes SET status = %s WHERE id = %s", ("Cancelada", rid))
                        conn.commit()
                        st.rerun()

    elif aba == "Medicações Agendadas":
        meds = pd.read_sql_query("SELECT * FROM ficha_medicacoes WHERE medicamento IS NOT NULL ORDER BY data_hora", get_engine())

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
                        c.execute("UPDATE ficha_medicacoes SET status = %s WHERE id = %s", ("Aplicada", med_id))
                        c.execute("""
                            UPDATE medicacoes_agendadas
                            SET status = %s
                            WHERE animal = %s AND medicamento = %s AND data_hora = %s
                        """, ("Aplicada", med["animal"], med["medicamento"], med["data_hora"]))
                        conn.commit()
                        st.success("Medicação marcada como aplicada.")
                        st.rerun()

                with colb2:
                    if st.button("🚫 Cancelar medicação", use_container_width=True):
                        c.execute("UPDATE ficha_medicacoes SET status = %s WHERE id = %s", ("Cancelada", med_id))
                        c.execute("""
                            UPDATE medicacoes_agendadas
                            SET status = %s
                            WHERE animal = %s AND medicamento = %s AND data_hora = %s
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
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            doadoras = pd.read_sql_query("SELECT * FROM doadoras WHERE egua_doadora IS NOT NULL", get_engine())

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
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    receptora, doadora, garanhao, cruzamento, br_data(data_transferencia),
                    dosagens, protocolo, br_data(previsao_parto),
                    br_data(confirmacao_prenhez), status, obs
                ))
                conn.commit()
                st.success("Controle da receptora salvo com sucesso!")

    elif aba == "Alertas Reprodutivos":
        doadoras = pd.read_sql_query("SELECT * FROM doadoras WHERE egua_doadora IS NOT NULL", get_engine())
        receptoras = pd.read_sql_query("SELECT * FROM receptoras WHERE receptora IS NOT NULL", get_engine())

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
        doadoras = pd.read_sql_query("SELECT * FROM doadoras WHERE egua_doadora IS NOT NULL", get_engine())
        st.dataframe(doadoras, use_container_width=True)

        st.markdown("### Receptoras")
        receptoras = pd.read_sql_query("SELECT * FROM receptoras WHERE receptora IS NOT NULL", get_engine())
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
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        str(venda_id), animal_nome, comprador_nome, str(i),
                        br_data(venc), str(valor_parcela), "", "Em aberto", ""
                    ))

                if status_venda == "Vendido":
                    c.execute("UPDATE animais SET status = %s WHERE nome = %s", ("Vendido", animal_nome))

                conn.commit()
                st.success("Venda salva e parcelas geradas com sucesso!")

    elif aba == "Recebimentos":
        df = pd.read_sql_query("SELECT * FROM recebimentos WHERE animal IS NOT NULL", get_engine())

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
                    SET status = %s, data_pagamento = %s, obs = %s
                    WHERE id = %s
                """, ("Pago", br_data(data_pagamento), obs, parcela_id))
                conn.commit()
                st.success("Parcela marcada como paga.")
        else:
            st.warning("Nenhum recebimento cadastrado.")

    elif aba == "Histórico de Vendas":
        df = pd.read_sql_query("SELECT * FROM vendas WHERE animal IS NOT NULL", get_engine())

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
        vendas = pd.read_sql_query("SELECT * FROM vendas WHERE animal IS NOT NULL", get_engine())

        if vendas.empty:
            st.warning("Cadastre uma venda primeiro.")
        else:
            vendas["descricao"] = vendas["id"].astype(str) + " - " + vendas["animal"] + " - " + vendas["comprador_nome"]
            esc = st.selectbox("Escolha a venda", vendas["descricao"].tolist())
            venda_id = esc.split(" - ")[0]
            venda = pd.read_sql_query("SELECT * FROM vendas WHERE id = %s", get_engine(), params=(venda_id,)).iloc[0]

            if st.button("Gerar Contrato PDF"):
                buffer = BytesIO()
                pdf = canvas.Canvas(buffer, pagesize=letter)
                largura, altura = letter

                if os.path.exists(LOGO):
                    pdf.drawImage(LOGO, 140, 700, width=320, height=90, preserveAspectRatio=True, mask="auto")

                y = 660
                pdf.setFont(_fonte(bold=True), 14)
                pdf.drawCentredString(largura / 2, y, _pdf_str("CONTRATO DE COMPRA E VENDA DE ANIMAL"))
                y -= 35

                pdf.setFont(_fonte(), 10)
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
                    pdf.drawString(50, y, _pdf_str(str(linha))[:110])
                    y -= 16
                    if y < 60:
                        pdf.showPage()
                        y = 750
                        pdf.setFont(_fonte(), 10)

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
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                nome, cpf, rg, telefone, email, endereco, cargo, setor,
                str(salario), br_data(data_admissao), status, documentos, obs
            ))
            conn.commit()
            st.success("Funcionário cadastrado com sucesso!")

    elif aba == "Funcionários Cadastrados":
        df = pd.read_sql_query("SELECT * FROM funcionarios WHERE nome IS NOT NULL AND nome != ''", get_engine())

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
        df = pd.read_sql_query("SELECT * FROM funcionarios WHERE nome IS NOT NULL AND nome != ''", get_engine())

        if df.empty:
            st.warning("Nenhum funcionário cadastrado.")
        else:
            df["descricao"] = df["id"].astype(str) + " - " + df["nome"].fillna("") + " - " + df["cargo"].fillna("")
            escolha = st.selectbox("Escolha o funcionário", df["descricao"].tolist())
            funcionario_id = escolha.split(" - ")[0]

            funcionario = pd.read_sql_query(
                "SELECT * FROM funcionarios WHERE id = %s", get_engine(),
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
                        SET nome = %s, cpf = %s, rg = %s, telefone = %s, email = %s,
                            endereco = %s, cargo = %s, setor = %s, salario = %s,
                            data_admissao = %s, status = %s, documentos = %s, obs = %s
                        WHERE id = %s
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
                        c.execute("DELETE FROM funcionarios WHERE id = %s", (funcionario_id,))
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
        st.markdown("### ⚙️ Configuração Twilio / WhatsApp Business")

        # ── Status atual ──────────────────────────────────────────────
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            st.metric("Biblioteca Twilio", "✅ Instalada" if Client is not None else "❌ Não instalada")
        with col_s2:
            st.metric("Credenciais", "✅ Configuradas" if twilio_configurado() else "❌ Não configuradas")
        with col_s3:
            numero_from = get_secret_value("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
            sandbox = "+14155238886" in numero_from
            st.metric("Modo", "🧪 Sandbox" if sandbox else "✅ Número real")

        st.markdown("---")

        # ── Passo a passo ─────────────────────────────────────────────
        st.markdown("### 📋 Como configurar — passo a passo")

        with st.expander("🧪 MODO SANDBOX (grátis para testar)", expanded=not twilio_configurado()):
            st.markdown("""
**Use para testar sem custo. Limitação: cada funcionário precisa se cadastrar manualmente.**

1. Acesse [twilio.com](https://www.twilio.com) e crie uma conta gratuita
2. No console Twilio, vá em **Messaging → Try it out → Send a WhatsApp message**
3. Cada funcionário deve enviar a mensagem **`join <código-do-sandbox>`** para o número **+1 (415) 523-8886**
4. Configure os secrets no Streamlit Cloud (**Manage app → Settings → Secrets**):
""")
            st.code("""TWILIO_ACCOUNT_SID = "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
TWILIO_AUTH_TOKEN  = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"
ADMIN_SENHA_INICIAL = "suasenhasegura"
""")
            st.caption("Account SID e Auth Token estão na página principal do console Twilio.")

        with st.expander("✅ NÚMERO REAL (produção — recomendado)", expanded=False):
            st.markdown("""
**Para uso definitivo. Funcionários recebem sem precisar se cadastrar no sandbox.**

**Opção A — Número Twilio dedicado** (mais simples):
1. No console Twilio, vá em **Phone Numbers → Buy a number**
2. Escolha um número com suporte a WhatsApp
3. Vá em **Messaging → Senders → WhatsApp Senders** e ative o número
4. Atualize o secret:
""")
            st.code('TWILIO_WHATSAPP_FROM = "whatsapp:+55119XXXXXXXX"  # seu número Twilio')
            st.markdown("""
**Opção B — Seu próprio número de WhatsApp Business** (mais profissional):
1. Crie uma conta no [Meta Business Manager](https://business.facebook.com)
2. Configure o **WhatsApp Business API** com seu número
3. Em **Twilio → Messaging → Senders → WhatsApp Senders**, conecte o número do Meta
4. Crie templates de mensagem aprovados pelo Meta (obrigatório para mensagens ativas)
5. Use o SID do template no campo `content_sid` da API Twilio
""")
            st.warning("Mensagens ativas (enviadas pelo sistema, não pelo usuário) exigem template aprovado pelo Meta. O processo de aprovação leva 1-3 dias.")

        with st.expander("🔔 Alertas automáticos (autorefresh)", expanded=False):
            st.markdown("""
**O sistema verifica automaticamente medicações a vencer a cada 5 minutos, enquanto o app estiver aberto no navegador.**

Para funcionar:
- Adicione `streamlit-autorefresh` no **requirements.txt** do seu repositório GitHub
- Configure as credenciais Twilio acima
- Deixe o app aberto em algum dispositivo (celular do admin, tablet no rancho, etc.)

Para alertas 100% automáticos (sem ninguém com o app aberto), use **GitHub Actions**:
""")
            st.code("""# .github/workflows/alertas.yml
name: Alertas WhatsApp
on:
  schedule:
    - cron: '*/30 * * * *'  # a cada 30 minutos
jobs:
  alertas:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: pip install twilio pandas
      - run: python scripts/enviar_alertas.py
        env:
          TWILIO_ACCOUNT_SID: ${{ secrets.TWILIO_ACCOUNT_SID }}
          TWILIO_AUTH_TOKEN: ${{ secrets.TWILIO_AUTH_TOKEN }}
          TWILIO_WHATSAPP_FROM: ${{ secrets.TWILIO_WHATSAPP_FROM }}
""")
            st.caption("Este workflow roda no GitHub sem custo (até 2000 minutos/mês no plano gratuito).")

        st.markdown("---")

        # ── Teste de envio ────────────────────────────────────────────
        st.markdown("### 🧪 Testar envio agora")
        if twilio_configurado():
            tel_teste = st.text_input("Número para teste (com DDD, ex: 87991234567)")
            msg_teste = st.text_area("Mensagem de teste", value="✅ Teste do sistema Rancho Recanto Verde. Twilio funcionando!")
            if st.button("📲 Enviar mensagem de teste", use_container_width=True):
                if tel_teste:
                    ok, sid, erro = enviar_whatsapp_twilio(tel_teste, msg_teste)
                    if ok:
                        st.success(f"✅ Enviado com sucesso! SID: {sid}")
                    else:
                        st.error(f"❌ Erro: {erro}")
                        if "sandbox" in erro.lower() or "unverified" in erro.lower() or "channel" in erro.lower():
                            st.info("💡 No sandbox, o destinatário precisa enviar 'join <código>' para o número Twilio antes de receber mensagens.")
                else:
                    st.warning("Informe um número para teste.")
        else:
            st.info("Configure as credenciais Twilio nos Secrets do Streamlit Cloud para habilitar o teste.")

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
                f"Olá, {funcionario_nome}!\n\n"
                f"🚨 Lembrete de medicação - Rancho Recanto Verde\n\n"
                f"Animal: {animal_nome}\n"
                f"Medicamento: {medicamento}\n"
                f"Dosagem/orientação: {dosagem}\n"
                f"Data e hora: {data_hora.strftime('%d/%m/%Y %H:%M')}\n\n"
                f"Favor confirmar a aplicação no sistema."
            )

            mensagem = st.text_area("Mensagem do WhatsApp", value=mensagem, height=180)

            if st.button("Salvar Agendamento"):
                c.execute("""
                    INSERT INTO medicacoes_agendadas
                    (animal, tipo_animal, medicamento, dosagem, data_hora,
                     funcionario, telefone, mensagem, status, alerta_gerado,
                     data_alerta, sid_twilio, erro_twilio, obs)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        df = pd.read_sql_query("SELECT * FROM medicacoes_agendadas WHERE status = 'Agendada'", get_engine())

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
                                    SET alerta_gerado = %s, data_alerta = %s, sid_twilio = %s, erro_twilio = %s
                                    WHERE id = %s
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
                                c.execute("UPDATE medicacoes_agendadas SET erro_twilio = %s WHERE id = %s", (erro, str(row["id"])))
                                conn.commit()
                                registrar_alerta_whatsapp(
                                    row["funcionario"], row["telefone"], "Medicação 1h antes",
                                    row["mensagem"], "Erro Twilio",
                                    erro_twilio=erro,
                                    obs=f"Animal: {row['animal']} | Medicamento: {row['medicamento']}"
                                )
                                st.error(f"Erro ao enviar: {erro}")

                        if st.button("Marcar medicação como aplicada", key=f"aplicada_{row['id']}", use_container_width=True):
                            c.execute("UPDATE medicacoes_agendadas SET status = %s WHERE id = %s", ("Aplicada", str(row["id"])))
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
        df_alertas = pd.read_sql_query("SELECT * FROM alertas_whatsapp WHERE funcionario IS NOT NULL", get_engine())
        df_medicacoes = pd.read_sql_query("SELECT * FROM medicacoes_agendadas WHERE animal IS NOT NULL", get_engine())

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

    tratamentos = pd.read_sql_query("SELECT animal, tipo, custo_total FROM tratamentos WHERE animal IS NOT NULL", get_engine())
    sanitario = pd.read_sql_query("SELECT animal, tipo, custo_total FROM sanitario WHERE animal IS NOT NULL", get_engine())

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

    animais_rel = pd.read_sql_query("SELECT * FROM animais WHERE nome IS NOT NULL AND nome != ''", get_engine())
    if not animais_rel.empty:
        resumo_tipo = animais_rel.groupby("tipo").size().reset_index(name="quantidade")
        st.bar_chart(resumo_tipo.set_index("tipo"))
        st.dataframe(resumo_tipo, use_container_width=True)
    else:
        st.info("Nenhum animal cadastrado.")

    st.markdown("---")
    st.markdown("### 💰 Vendas e recebimentos")

    vendas_rel = pd.read_sql_query("SELECT * FROM vendas WHERE animal IS NOT NULL", get_engine())
    receb_rel = pd.read_sql_query("SELECT * FROM recebimentos WHERE animal IS NOT NULL", get_engine())

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
    titulo_pagina("⚙️ Admin / Usuários", "Cadastro de usuários, senhas e auditoria do sistema")

    if st.session_state.usuario.get("perfil") != "Administrador":
        st.error("Apenas administradores podem acessar esta área.")
        st.stop()

    aba = st.radio(
        "Opção",
        ["👤 Cadastrar Usuário", "📋 Usuários Cadastrados", "🔑 Resetar Senha", "📜 Auditoria"],
        horizontal=True
    )

    # ── CADASTRAR USUÁRIO ───────────────────────────────
    if aba == "👤 Cadastrar Usuário":
        st.markdown("### Novo usuário")
        col1, col2 = st.columns(2)
        with col1:
            nome_usuario  = st.text_input("Nome de login *")
            senha_usuario = st.text_input("Senha *", type="password")
            perfil        = st.selectbox("Perfil", list(PERFIS.keys()))
        with col2:
            ativo = st.selectbox("Ativo", ["Sim", "Não"])
            st.info("Permissões liberadas automaticamente pelo perfil.")
            st.caption("Permissões: " + ", ".join(PERFIS[perfil]))

        if st.button("💾 Salvar Usuário", use_container_width=True):
            if not nome_usuario or not senha_usuario:
                st.error("Informe nome e senha.")
            else:
                existente = pd.read_sql_query(
                    "SELECT id FROM usuarios WHERE nome = %s", get_engine(), params=(nome_usuario,)
                )
                if not existente.empty:
                    st.error("Já existe usuário com esse nome.")
                else:
                    c.execute("""
                        INSERT INTO usuarios (nome, senha_hash, perfil, permissoes, ativo)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (nome_usuario, hash_senha(senha_usuario), perfil, "|".join(PERFIS[perfil]), ativo))
                    conn.commit()
                    registrar_auditoria("Admin", "Cadastro de usuário", f"Usuário '{nome_usuario}' criado com perfil '{perfil}'")
                    st.success(f"✅ Usuário '{nome_usuario}' cadastrado com sucesso!")

    # ── USUÁRIOS CADASTRADOS ────────────────────────────
    elif aba == "📋 Usuários Cadastrados":
        df = pd.read_sql_query("SELECT id, nome, perfil, ativo FROM usuarios ORDER BY nome", get_engine())
        if not df.empty:
            st.dataframe(df.rename(columns={"id":"ID","nome":"Usuário","perfil":"Perfil","ativo":"Ativo"}),
                        use_container_width=True, hide_index=True)

            st.markdown("### Editar usuário")
            opcoes_u = (df["id"].astype(str) + " — " + df["nome"]).tolist()
            escolha_u = st.selectbox("Selecione", opcoes_u)
            usuario_id = escolha_u.split(" — ")[0]
            usuario_row = pd.read_sql_query("SELECT * FROM usuarios WHERE id = %s", get_engine(), params=(usuario_id,)).iloc[0]

            col1, col2 = st.columns(2)
            with col1:
                novo_perfil = st.selectbox("Perfil", list(PERFIS.keys()),
                    index=list(PERFIS.keys()).index(usuario_row["perfil"]) if usuario_row["perfil"] in PERFIS else 0)
                novo_ativo  = st.selectbox("Ativo", ["Sim", "Não"],
                    index=0 if usuario_row["ativo"] == "Sim" else 1)
            with col2:
                perms_atuais = str(usuario_row["permissoes"] or "").split("|")
                novas_perms  = st.multiselect("Permissões customizadas", TODAS_PERMISSOES,
                    default=[p for p in perms_atuais if p in TODAS_PERMISSOES])

            col_b1, col_b2 = st.columns(2)
            with col_b1:
                if st.button("💾 Atualizar", use_container_width=True):
                    c.execute("""
                        UPDATE usuarios SET perfil=%s, permissoes=%s, ativo=%s WHERE id=%s
                    """, (novo_perfil, "|".join(novas_perms), novo_ativo, usuario_id))
                    conn.commit()
                    registrar_auditoria("Admin", "Edição de usuário", f"Usuário ID {usuario_id} atualizado: perfil={novo_perfil}, ativo={novo_ativo}")
                    st.success("✅ Usuário atualizado!")
            with col_b2:
                if st.button("🗑️ Desativar usuário", use_container_width=True):
                    c.execute("UPDATE usuarios SET ativo='Não' WHERE id=%s", (usuario_id,))
                    conn.commit()
                    registrar_auditoria("Admin", "Desativação de usuário", f"Usuário ID {usuario_id} desativado")
                    st.success("Usuário desativado.")
                    st.rerun()
        else:
            st.warning("Nenhum usuário cadastrado.")

    # ── RESETAR SENHA ───────────────────────────────────
    elif aba == "🔑 Resetar Senha":
        titulo_pagina("🔑 Resetar Senha", "Redefina a senha de qualquer usuário — use quando o colaborador esquecer")

        st.markdown("""
<div style='background:rgba(232,184,75,0.1);border:1px solid rgba(232,184,75,0.25);
border-left:4px solid #e8b84b;border-radius:0 10px 10px 0;padding:12px 16px;margin-bottom:16px'>
  <div style='font-weight:500;color:#e8b84b;margin-bottom:4px'>📋 Procedimento para senha esquecida:</div>
  <div style='font-size:0.82rem;color:var(--muted);line-height:1.8'>
    1. Selecione o usuário abaixo<br>
    2. Defina uma senha provisória simples (ex: o nome do colaborador)<br>
    3. Clique em <strong>Resetar Senha</strong><br>
    4. Informe a senha provisória ao colaborador pessoalmente<br>
    5. Peça para ele trocar a senha no próximo acesso em <strong>Meu Perfil</strong>
  </div>
</div>
""", unsafe_allow_html=True)

        df_u = pd.read_sql_query("SELECT id, nome, perfil FROM usuarios ORDER BY nome", get_engine())
        if not df_u.empty:
            opcoes_reset = (df_u["nome"] + " (" + df_u["perfil"] + ")").tolist()
            idx_reset = st.selectbox("Selecione o usuário", range(len(opcoes_reset)),
                                     format_func=lambda i: opcoes_reset[i])
            usuario_reset_id = str(df_u.iloc[idx_reset]["id"])
            usuario_reset_nome = df_u.iloc[idx_reset]["nome"]

            col_r1, col_r2 = st.columns(2)
            with col_r1:
                nova_senha_reset = st.text_input("Nova senha provisória *", type="password",
                                                  placeholder="Ex: rancho2026")
            with col_r2:
                confirmar_reset = st.text_input("Confirmar nova senha *", type="password")

            if st.button("🔑 Resetar Senha", use_container_width=True):
                if not nova_senha_reset:
                    st.error("Informe a nova senha.")
                elif nova_senha_reset != confirmar_reset:
                    st.error("As senhas não coincidem.")
                elif len(nova_senha_reset) < 4:
                    st.error("Senha deve ter pelo menos 4 caracteres.")
                else:
                    c.execute(
                        "UPDATE usuarios SET senha_hash = %s WHERE id = %s",
                        (hash_senha(nova_senha_reset), usuario_reset_id)
                    )
                    conn.commit()
                    registrar_auditoria("Admin", "Reset de senha", f"Senha de '{usuario_reset_nome}' redefinida pelo administrador")
                    st.success(f"✅ Senha de **{usuario_reset_nome}** redefinida com sucesso!")
                    st.info(f"📱 Informe ao colaborador que a nova senha provisória está definida. Peça para trocar no próximo acesso.")
        else:
            st.warning("Nenhum usuário cadastrado.")

    # ── AUDITORIA ───────────────────────────────────────
    elif aba == "📜 Auditoria":
        titulo_pagina("📜 Auditoria do Sistema", "Registro de todas as ações realizadas no sistema")

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            filtro_usuario_aud = st.text_input("Filtrar usuário")
        with col_f2:
            filtro_modulo_aud  = st.text_input("Filtrar módulo")
        with col_f3:
            filtro_acao_aud    = st.text_input("Filtrar ação")

        try:
            df_aud = pd.read_sql_query(
                "SELECT * FROM auditoria ORDER BY id DESC LIMIT 500",
                get_engine()
            )
        except Exception:
            df_aud = pd.DataFrame()

        if not df_aud.empty:
            if filtro_usuario_aud:
                df_aud = df_aud[df_aud["usuario"].str.contains(filtro_usuario_aud, case=False, na=False)]
            if filtro_modulo_aud:
                df_aud = df_aud[df_aud["modulo"].str.contains(filtro_modulo_aud, case=False, na=False)]
            if filtro_acao_aud:
                df_aud = df_aud[df_aud["acao"].str.contains(filtro_acao_aud, case=False, na=False)]

            st.metric("Registros encontrados", len(df_aud))

            # Resumo por usuário
            if not df_aud.empty:
                st.markdown("#### Atividade por usuário")
                resumo = df_aud.groupby("usuario")["acao"].count().reset_index()
                resumo.columns = ["Usuário", "Ações registradas"]
                resumo = resumo.sort_values("Ações registradas", ascending=False)
                st.dataframe(resumo, use_container_width=True, hide_index=True)

                st.markdown("#### Log completo")
                cols_show = ["data_hora", "usuario", "perfil", "modulo", "acao", "descricao"]
                cols_show = [c0 for c0 in cols_show if c0 in df_aud.columns]
                st.dataframe(
                    df_aud[cols_show].rename(columns={
                        "data_hora": "Data/Hora", "usuario": "Usuário",
                        "perfil": "Perfil", "modulo": "Módulo",
                        "acao": "Ação", "descricao": "Descrição"
                    }),
                    use_container_width=True, hide_index=True
                )

                st.download_button(
                    "📥 Exportar Auditoria (Excel)",
                    data=gerar_excel(df_aud),
                    file_name=f"auditoria_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        else:
            st.info("Nenhuma ação registrada ainda. As ações serão registradas automaticamente a partir de agora.")



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

            existente = pd.read_sql_query(
                "SELECT * FROM usuarios WHERE nome = %s", get_engine(),
                params=(nome_usuario,)
            )

            if not existente.empty:
                st.error("Já existe usuário com esse nome.")

            c.execute("""
                INSERT INTO usuarios (nome, senha_hash, perfil, permissoes, ativo)
                VALUES (%s, %s, %s, %s, %s)
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
        df = pd.read_sql_query("SELECT id, nome, perfil, permissoes, ativo FROM usuarios", get_engine())

        if not df.empty:
            st.dataframe(df, use_container_width=True)

            st.markdown("### Editar usuário")
            usuario_id = st.selectbox("ID do usuário", df["id"].astype(str).tolist())
            usuario = pd.read_sql_query("SELECT * FROM usuarios WHERE id = %s", get_engine(), params=(usuario_id,)).iloc[0]

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
                    SET perfil = %s, permissoes = %s, ativo = %s
                    WHERE id = %s
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
        df = pd.read_sql_query("SELECT id, nome FROM usuarios", get_engine())

        if not df.empty:
            usuario_id = st.selectbox("Usuário", df["id"].astype(str).tolist())
            nova_senha = st.text_input("Nova senha", type="password")

            if st.button("Alterar Senha"):
                if not nova_senha:
                    st.error("Informe a nova senha.")

                c.execute(
                    "UPDATE usuarios SET senha_hash = %s WHERE id = %s",
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

        animal = pd.read_sql_query("SELECT * FROM animais WHERE nome = %s", get_engine(), params=(animal_nome,)).iloc[0]
        pesagens = pd.read_sql_query("SELECT * FROM pesagens WHERE animal = %s", get_engine(), params=(animal_nome,))
        sanitario = pd.read_sql_query("SELECT * FROM sanitario WHERE animal = %s", get_engine(), params=(animal_nome,))
        tratamentos = pd.read_sql_query("SELECT * FROM tratamentos WHERE animal = %s", get_engine(), params=(animal_nome,))
        vendas = pd.read_sql_query("SELECT * FROM vendas WHERE animal = %s", get_engine(), params=(animal_nome,))

        if st.button("Gerar PDF"):
            _init_fonte_pdf()
            buffer = BytesIO()
            pdf = canvas.Canvas(buffer, pagesize=letter)

            if os.path.exists(LOGO):
                pdf.drawImage(LOGO, 130, 690, width=350, height=100, preserveAspectRatio=True, mask="auto")

            pdf.setFont(_fonte(bold=True), 14)
            pdf.drawString(50, 650, _pdf_str("FICHA DO ANIMAL"))

            pdf.setFont(_fonte(), 10)
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
                pdf.drawString(50, y, _pdf_str(f"{titulo}: {valor if valor else ''}"))
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

                pdf.setFont(_fonte(bold=True), 13)
                pdf.drawString(50, y, _pdf_str(titulo))
                y -= 20
                pdf.setFont(_fonte(), 9)

                if not df_secao.empty:
                    for _, row in df_secao.iterrows():
                        pdf.drawString(50, y, _pdf_str(formatador(row))[:115])
                        y -= 15
                        if y < 70:
                            pdf.showPage()
                            y = 750
                            pdf.setFont(_fonte(), 9)
                else:
                    pdf.drawString(50, y, _pdf_str("Nenhum registro."))
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
