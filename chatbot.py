import requests
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException

# --- Configurações e Variáveis Globais ---
API_BASE_URL = "https://35d7-2804-d59-f728-ac00-9c12-976e-cbf6-3034.ngrok-free.app" # URL atualizada do ngrok
conversas = {}
driver = webdriver.Chrome()

# --- Funções de Lógica (As mesmas que já testamos) ---
def obter_servicos():
    try:
        response = requests.get(f"{API_BASE_URL}/api/services")
        return response.json() if response.status_code == 200 else None
    except: return None

def obter_profissionais():
    try:
        response = requests.get(f"{API_BASE_URL}/api/professionals")
        return response.json() if response.status_code == 200 else None
    except: return None

# --- Funções de Comunicação (Atualizadas e Robustas) ---
def enviar_mensagem_whatsapp(texto):
    """Encontra a caixa de texto, digita e envia a mensagem."""
    try:
        # Usando o seletor que testamos e funcionou!
        caixa_de_texto_selector = "div[contenteditable='true'][data-tab='10']"
        caixa_de_texto = driver.find_element(By.CSS_SELECTOR, caixa_de_texto_selector)
        caixa_de_texto.clear()
        for linha in texto.split('\n'):
            caixa_de_texto.send_keys(linha)
            caixa_de_texto.send_keys(Keys.SHIFT, Keys.ENTER)
        caixa_de_texto.send_keys(Keys.ENTER)
        return True
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")
        return False

# --- O Motor Principal do Chatbot (com a nova lógica de leitura) ---
def processar_mensagem(cliente_id, texto_recebido):
    estado_atual = conversas.get(cliente_id, {"etapa": "inicio"})
    etapa = estado_atual.get("etapa")
    print(f"Processando para {cliente_id} na etapa {etapa}...")

    # A lógica de conversa continua a mesma...
    if etapa == "inicio":
        servicos = obter_servicos()
        if servicos:
            mensagem = "Olá! Bem-vindo ao agendamento Fluxo. Qual serviço deseja agendar?\n"
            for i, s in enumerate(servicos, start=1):
                mensagem += f"\n*{i}* - {s['name']}"
            enviar_mensagem_whatsapp(mensagem)
            conversas[cliente_id] = {"etapa": "aguardando_servico", "dados_servicos": servicos}
    
    elif etapa == "aguardando_servico":
        try:
            escolha_idx = int(texto_recebido) - 1
            servico_escolhido = estado_atual["dados_servicos"][escolha_idx]
            profissionais = obter_profissionais()
            profissionais_disponiveis = [p for p in profissionais if any(s['id'] == servico_escolhido['id'] for s in p.get('services', []))]
            
            if profissionais_disponiveis:
                mensagem = f"Ótima escolha: *{servico_escolhido['name']}*.\n\nCom qual profissional você gostaria de agendar?\n"
                for i, p in enumerate(profissionais_disponiveis, start=1):
                    mensagem += f"\n*{i}* - {p['name']}"
                enviar_mensagem_whatsapp(mensagem)
                conversas[cliente_id]["etapa"] = "aguardando_profissional"
                # ... (aqui continuaria a lógica para as próximas etapas)
            else:
                enviar_mensagem_whatsapp("Desculpe, não há profissionais que realizam este serviço.")
                conversas.pop(cliente_id, None)
        except (ValueError, IndexError):
            enviar_mensagem_whatsapp("Opção inválida. Por favor, digite apenas o número de um dos serviços listados.")

# --- Ponto de Partida e Loop Principal ---
if __name__ == '__main__':
    driver.get('https://web.whatsapp.com')
    print("--- Robô do Fluxo Iniciado ---")
    print("Por favor, escaneie o QR Code com o telemóvel que será o número do robô.")
    
    # Espera até que o usuário escaneie o QR Code e a página principal carregue
    wait = WebDriverWait(driver, 60)
    wait.until(EC.presence_of_element_located((By.ID, "pane-side"))) # Espera o painel lateral carregar
    
    print("Login bem-sucedido! A escutar por novas mensagens na conversa aberta...")
    
    ultima_mensagem_processada = "" # Guarda o texto da última mensagem que processamos

    while True:
        try:
            # Pega TODAS as mensagens na conversa aberta
            mensagens = driver.find_elements(By.CSS_SELECTOR, ".message-in span.selectable-text")
            if mensagens:
                # Pega o texto da última mensagem
                texto_ultima_mensagem = mensagens[-1].text
                
                # Se a última mensagem for diferente da que já processamos...
                if texto_ultima_mensagem != ultima_mensagem_processada:
                    print(f"Nova mensagem detectada: '{texto_ultima_mensagem}'")
                    # Usamos 'cliente_ativo' como ID, já que estamos a olhar para a conversa aberta
                    processar_mensagem("cliente_ativo", texto_ultima_mensagem)
                    ultima_mensagem_processada = texto_ultima_mensagem # Atualiza a última mensagem
        except Exception as e:
            # Se ocorrer um erro (ex: a conversa não tem mensagens), apenas ignoramos e tentamos de novo
            pass
        
        time.sleep(3) # Verifica por novas mensagens a cada 3 segundos