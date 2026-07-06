"""
Backup diário de todas as tabelas do banco (Supabase) para CSV.

Roda automaticamente via GitHub Actions (.github/workflows/backup-diario.yml),
sem depender de ninguém estar com o app aberto. Salva cada tabela como um CSV
dentro de backups/<data>/, e remove pastas de backup com mais de 30 dias para
não deixar o repositório crescendo pra sempre.

Uso local (opcional): defina a variável de ambiente DATABASE_URL e rode
`python scripts/backup_diario.py`.
"""
import os
import sys
import shutil
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
import pandas as pd

RETENCAO_DIAS = 30


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERRO: variável de ambiente DATABASE_URL não configurada.")
        sys.exit(1)

    hoje = datetime.now().strftime("%Y-%m-%d")
    pasta_destino = os.path.join("backups", hoje)
    os.makedirs(pasta_destino, exist_ok=True)

    conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor, sslmode="require", connect_timeout=15)
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    tabelas = [r["table_name"] for r in cur.fetchall()]

    total_linhas = 0
    for tabela in tabelas:
        cur.execute(f"SELECT * FROM {tabela}")
        linhas = cur.fetchall()
        df = pd.DataFrame([dict(r) for r in linhas])
        caminho = os.path.join(pasta_destino, f"{tabela}.csv")
        df.to_csv(caminho, index=False, encoding="utf-8-sig")
        total_linhas += len(df)
        print(f"  {tabela}.csv -> {len(df)} linha(s)")

    conn.close()
    print(f"Backup salvo em {pasta_destino}/ ({len(tabelas)} tabelas, {total_linhas} linhas no total)")

    # Remove backups mais antigos que RETENCAO_DIAS
    limite = datetime.now() - timedelta(days=RETENCAO_DIAS)
    raiz_backups = "backups"
    if os.path.isdir(raiz_backups):
        for nome_pasta in os.listdir(raiz_backups):
            caminho_pasta = os.path.join(raiz_backups, nome_pasta)
            if not os.path.isdir(caminho_pasta):
                continue
            try:
                data_pasta = datetime.strptime(nome_pasta, "%Y-%m-%d")
            except ValueError:
                continue
            if data_pasta < limite:
                shutil.rmtree(caminho_pasta)
                print(f"Backup antigo removido: {caminho_pasta}")


if __name__ == "__main__":
    main()
