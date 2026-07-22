import os
import shutil
from src.core.logger import log

def clear_logs_directory():
    """
    Exclui todos os arquivos e pastas no diretório logs,
    exceto o arquivo de log atual (automation.log) se estiver em uso.
    """
    logs_dir = "logs"
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
        return

    log.info(f"Limpando diretório de saída: {logs_dir}...")
    
    for filename in os.listdir(logs_dir):
        file_path = os.path.join(logs_dir, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                # Se for o log atual, tentamos excluir, mas ignoramos se falhar (em uso no Windows)
                if filename == "automation.log":
                    continue # Melhor não mexer no log principal para evitar erros de permissão
                
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            log.warning(f"Não foi possível excluir {file_path}: {e}")

    log.success("Limpeza concluída com sucesso.")
