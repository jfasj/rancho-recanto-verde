import streamlit as st
import sqlite3
from datetime import datetime, timedelta

# =============================
# CONFIG
# =============================
st.set_page_config(page_title="Rancho Recanto Verde", layout="wide")

# =============================
# BANCO
# =============================
conn = sqlite3.connect("rancho.db", check_same_thread=False)
c = conn.cursor()

# Tabelas
c.execute("""
CREATE TABLE IF NOT EXISTS funcionarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT,
    telefone TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS tratamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    animal TEXT,
    medicamento TEXT,
    data_hora TEXT,
    funcionario TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mensagem TEXT,
    telefone TEXT,
    data_envio TEXT,
    enviado INTEGER DEFAULT 0
)
""")

conn.commit()

# =============================
# MENU
# =============================
menu = st.sidebar.radio("Menu", [
    "Dashboard",
    "Funcionários",
    "Veterinário / Tratamentos",
    "📲 Alertas WhatsApp"
])

# =============================
# DASHBOARD
# =============================
if menu == "Dashboard":
    st.title("📊 Dashboard")

    total_func = c.execute("SELECT COUNT(*) FROM funcionarios").fetchone()[0]
    total_trat = c.execute("SELECT COUNT(*) FROM tratamentos").fetchone()[0]
    total_alert = c.execute("SELECT COUNT(*) FROM alertas").fetchone()[0]

    col1, col2, col3 = st.columns(3)

    col1.metric("Funcionários", total_func)
    col2.metric("Tratamentos", total_trat)
    col3.metric("Alertas", total_alert)

# =============================
# FUNCIONÁRIOS
# =============================
elif menu == "Funcionários":
    st.title("👨‍🌾 Cadastro de Funcionários")

    nome = st.text_input("Nome")
    telefone = st.text_input("Telefone (com DDD)")

    if st.button("Cadastrar"):
        c.execute("INSERT INTO funcionarios (nome, telefone) VALUES (?,?)", (nome, telefone))
        conn.commit()
        st.success("Funcionário cadastrado!")

    st.subheader("Lista")
    dados = c.execute("SELECT * FROM funcionarios").fetchall()
    st.table(dados)

# =============================
# TRATAMENTOS
# =============================
elif menu == "Veterinário / Tratamentos":
    st.title("💉 Registrar Tratamento")

    animal = st.text_input("Animal")
    medicamento = st.text_input("Medicamento")

    data = st.date_input("Data")
    hora = st.time_input("Hora")

    funcionarios = c.execute("SELECT nome FROM funcionarios").fetchall()
    lista_func = [f[0] for f in funcionarios]

    funcionario = st.selectbox("Funcionário responsável", lista_func)

    if st.button("Salvar Tratamento"):
        data_hora = datetime.combine(data, hora)

        c.execute("""
        INSERT INTO tratamentos (animal, medicamento, data_hora, funcionario)
        VALUES (?,?,?,?)
        """, (animal, medicamento, str(data_hora), funcionario))

        # Buscar telefone
        tel = c.execute("SELECT telefone FROM funcionarios WHERE nome=?", (funcionario,)).fetchone()

        if tel:
            telefone = tel[0]

            # ALERTA 1 HORA ANTES
            envio = data_hora - timedelta(hours=1)

            mensagem = f"""
🐴 Rancho Recanto Verde

⏰ Lembrete de medicação

Animal: {animal}
Medicamento: {medicamento}
Horário: {data_hora.strftime('%d/%m %H:%M')}

Responsável: {funcionario}
"""

            c.execute("""
            INSERT INTO alertas (mensagem, telefone, data_envio)
            VALUES (?,?,?)
            """, (mensagem, telefone, str(envio)))

        conn.commit()
        st.success("Tratamento salvo + alerta criado!")

# =============================
# ALERTAS WHATSAPP
# =============================
elif menu == "📲 Alertas WhatsApp":
    st.title("📲 Alertas de WhatsApp")

    agora = datetime.now()

    alertas = c.execute("SELECT * FROM alertas").fetchall()

    for alerta in alertas:
        id_, msg, tel, data_envio, enviado = alerta

        data_envio_dt = datetime.fromisoformat(data_envio)

        col1, col2 = st.columns([4,1])

        col1.info(f"""
📱 {tel}
⏰ {data_envio_dt.strftime('%d/%m %H:%M')}
📄 {msg}
""")

        if enviado == 0:
            if col2.button("Enviar", key=id_):

                # LINK WHATSAPP
                link = f"https://wa.me/55{tel}?text={msg.replace(' ', '%20')}"

                c.execute("UPDATE alertas SET enviado=1 WHERE id=?", (id_,))
                conn.commit()

                st.success("Clique abaixo para enviar 👇")
                st.markdown(f"[📲 Enviar WhatsApp]({link})")

        else:
            col2.success("Enviado")
