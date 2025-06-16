import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException

# Inicia o Chrome
driver = webdriver.Chrome()
driver.get('https://web.whatsapp.com')

print("--- Teste de Envio do Robô Fluxo (v2) ---")
print("\n[AÇÃO NECESSÁRIA] Por favor, escaneie o QR Code se for solicitado.")
print("Aguardando login completo... (Você tem até 60 segundos)")
time.sleep(60)

print("\n[AÇÃO NECESSÁRIA] Agora, por favor, use o seu mouse para ABRIR A CONVERSA para a qual deseja enviar a mensagem de teste.")
print("O robô tentará enviar a mensagem em 20 segundos...")
time.sleep(20)

try:
    texto_teste = "Olá! Isto é um teste de envio automático do Robô Fluxo v2.0!"
    
    # --- AQUI ESTÁ A CORREÇÃO ---
    # Usando um seletor CSS mais robusto e moderno para encontrar a caixa de texto
    caixa_de_texto_selector = "div[contenteditable='true'][data-tab='10']"
    caixa_de_texto = driver.find_element(By.CSS_SELECTOR, caixa_de_texto_selector)
    # --- FIM DA CORREÇÃO ---
    
    caixa_de_texto.send_keys(texto_teste)
    caixa_de_texto.send_keys(Keys.ENTER)
    
    print("\n[SUCESSO] Mensagem de teste enviada!")

except NoSuchElementException:
    print(f"\n[FALHA] Não foi possível encontrar a caixa de texto usando o novo seletor. O WhatsApp pode ter atualizado seu código novamente.")
except Exception as e:
    print(f"\n[FALHA] Ocorreu um erro inesperado: {e}")

input("\nTeste concluído. Pressione Enter para fechar o navegador...")
driver.quit()