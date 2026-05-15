import subprocess
import xml.etree.ElementTree as ET
import time
import asyncio
from playwright.async_api import async_playwright
import os
import random
import re
from datetime import datetime
import urllib.request
import json
from PIL import Image
import requests

# Mensagem enviada ao final de cada execução com o resumo de pontos e status.
TELEGRAM_TOKEN = "8562320860:AAGPanUnsKtPBM7U4DvSp7IjMYKcGbh6RwU"
TELEGRAM_CHAT_ID = "1062820066"

# ==========================================
# FUNÇÕES DE BUSCA E WIKIPEDIA
# ==========================================

def get_wikipedia_random_terms(count=50):
    url = f"https://pt.wikipedia.org/w/api.php?action=query&list=random&rnnamespace=0&rnlimit={count}&format=json"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return [article['title'] for article in data['query']['random']]
    except Exception as e:
        print(f"Erro ao buscar termos na Wikipedia: {e}")
        return ["Noticias do dia Brasil", "Como fazer bolo", "Clima amanhã", "Cotação do dólar"] * 10

SEARCH_TERMS_QUEUE = []

def get_random_search_term():
    global SEARCH_TERMS_QUEUE
    if not SEARCH_TERMS_QUEUE:
        SEARCH_TERMS_QUEUE = get_wikipedia_random_terms(50)
    return SEARCH_TERMS_QUEUE.pop()

async def human_delay(min_ms=2000, max_ms=5000):
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000.0)

async def handle_new_pages(context, default_pages_count):
    await human_delay(3000, 6000)
    if len(context.pages) > default_pages_count:
        new_page = context.pages[-1]
        try:
            await new_page.evaluate("window.scrollBy(0, window.innerHeight / 2)")
            await human_delay(1500, 3000)
        except: pass
        await new_page.close()

async def get_remaining_searches(page):
    print("[Debug] Navegando para rewards.bing.com...")
    await page.goto("https://rewards.bing.com/", wait_until="domcontentloaded", timeout=15000)
    await human_delay(3000, 5000)

    # --- Passo 1: Tentar clicar na aba "Status" (novo layout) ---
    try:
        print("[Debug] Procurando aba 'Status'...")
        # Tenta pelos seletores mais comuns de aba no novo layout
        status_tab_selectors = [
            "button:has-text('Status')",
            "a:has-text('Status')",
            "li:has-text('Status')",
            "[role='tab']:has-text('Status')",
            "[aria-label*='Status']",
        ]
        for sel in status_tab_selectors:
            try:
                tab = page.locator(sel).first
                if await tab.count() > 0:
                    print(f"[Debug] Aba 'Status' encontrada ({sel}). Clicando...")
                    await tab.click(timeout=4000)
                    await human_delay(2000, 3500)
                    break
            except: continue
    except: pass

    # --- Passo 2: Tentar clicar no link "Ver detalhamento dos pontos" ---
    try:
        print("[Debug] Procurando link de detalhamento...")
        breakdown_selectors = [
            'a.pointbreakdownlink',                          # layout antigo
            'a[href*="breakdown"]',
            'a[href*="pointsbreakdown"]',
            "a:has-text('detalhamento')",
            "a:has-text('Detalhamento')",
            "button:has-text('detalhamento')",
            "a:has-text('Ver detalhamento')",
        ]
        clicked = False
        for sel in breakdown_selectors:
            try:
                link = page.locator(sel).first
                if await link.count() > 0:
                    print(f"[Debug] Link detalhamento encontrado ({sel}). Clicando...")
                    await link.click(timeout=5000)
                    await human_delay(3000, 5000)
                    clicked = True
                    break
            except: continue

        # Fallback: busca por texto parcial via get_by_text
        if not clicked:
            try:
                link_txt = page.get_by_text(re.compile(r'detalhamento|breakdown', re.IGNORECASE))
                if await link_txt.count() > 0:
                    print("[Debug] Link detalhamento encontrado por texto. Clicando...")
                    await link_txt.first.click(timeout=5000)
                    await human_delay(3000, 5000)
            except: pass
    except: pass

    # --- Passo 3: Ler pontos do corpo da página ---
    pc_pts, mob_pts = 0, 0
    try:
        body_text = await page.inner_text("body", timeout=8000)

        # Padrões: "X / 90", "X/90", etc.
        pc_match  = re.search(r'(\d+)\s*/\s*90',  body_text)
        mob_match = re.search(r'(\d+)\s*/\s*60',  body_text)

        pc_pts  = int(pc_match.group(1))  if pc_match  else 0
        mob_pts = int(mob_match.group(1)) if mob_match else 0

        # Se ainda não achou, tenta via inner_html (valores às vezes ficam em atributos)
        if pc_pts == 0 and mob_pts == 0:
            html_text = await page.content()
            pc_match2  = re.search(r'(\d+)\s*/\s*90',  html_text)
            mob_match2 = re.search(r'(\d+)\s*/\s*60',  html_text)
            pc_pts  = int(pc_match2.group(1))  if pc_match2  else 0
            mob_pts = int(mob_match2.group(1)) if mob_match2 else 0
    except:
        pc_pts, mob_pts = 0, 0

    pc_needed  = max(0, (90 - pc_pts)  // 3)
    mob_needed = max(0, (60 - mob_pts) // 3)
    print(f"[Debug] Pts PC: {pc_pts}/90 (Faltam {pc_needed}), Pts Mob: {mob_pts}/60 (Faltam {mob_needed})")

    return pc_pts, mob_pts, pc_needed, mob_needed

async def perform_searches(context, count, device_name="PC"):
    if count <= 0: return
    page = context.pages[0] if context.pages else await context.new_page()
    for i in range(count):
        term_raw = get_random_search_term()
        # Remove caracteres que o terminal Windows não aguenta imprimir
        term = term_raw.encode('ascii', 'ignore').decode('ascii')
        print(f"[{device_name}] Pesquisa {i+1}/{count}: '{term}'")
        try:
            # Pula a tela inicial do Bing e navega diretamente para a URL de pesquisa, 
            # imitando exatamente o comportamento de digitar na barra de endereços do Edge.
            import urllib.parse
            # form=CHROMN é um dos códigos que o Edge usa ao pesquisar pela barra de endereços
            search_url = f"https://www.bing.com/search?q={urllib.parse.quote(term)}&form=CHROMN"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
            
            # Aguarda a página renderizar bem para o scroll funcionar
            await human_delay(1500, 3000)
            
            # Scroll mais natural para simular leitura
            try:
                await page.evaluate(f"window.scrollBy(0, {random.randint(300, 700)})")
                await human_delay(1000, 2000)
                await page.evaluate(f"window.scrollBy(0, {random.randint(100, 400)})")
            except:
                pass
                
            await human_delay(7000, 10000)
        except Exception as e: 
            print(f"Erro pesquisa: {e}")

async def do_daily_sets(context, default_pages_count):
    print("\n--- INICIANDO CONJUNTO DIÁRIO (E EXTRAÇÃO DE LIMITES) ---")
    page = context.pages[0] if context.pages else await context.new_page()
    print("[Debug] Acessando painel de Rewards...")
    try:
        await page.goto("https://rewards.bing.com/?form=dash_2", wait_until="domcontentloaded", timeout=15000)
    except Exception as e:
        print(f"[Debug] Tempo esgotado no carregamento inicial (ignorado): {e}")

    await human_delay(4000, 6000)

    print("[Debug] Checando e fechando modais de boas-vindas/cookies...")
    try:
        if await page.locator("button#bnp_btn_accept").count() > 0:
            await page.locator("button#bnp_btn_accept").click(timeout=3000)
            await human_delay(1000, 2000)
        close_btn = page.locator("button.ms-Dialog-button--close, button[aria-label='Fechar'], button#modal-host-close")
        if await close_btn.count() > 0:
            await close_btn.first.click(timeout=3000)
            await human_delay(1000, 2000)
    except: pass

    print("[Debug] Processando Daily Sets...")
    daily_sets = await page.locator("mee-rewards-daily-set-item-content").all()
    for i, card in enumerate(daily_sets[:3]):
        try:
            html = await card.evaluate("el => el.outerHTML")
            if "icon-check" not in html and "SkypeCircleCheck" not in html:
                print(f"[Debug] Clicando no Conjunto Diário {i+1}...")
                await card.click(force=True, timeout=3000)
                await handle_new_pages(context, default_pages_count)
            else:
                print(f"[Debug] Card Diario {i+1} ja concluido.")
        except Exception as e:
            print(f"[Debug] Erro ao processar Card Diario {i+1}: {e}")

    print("[Debug] Buscando Mais Atividades (rolando a tela)...")
    await page.evaluate("window.scrollBy(0, 800)")
    await human_delay(2000, 4000)

    more_activities = await page.locator("mee-rewards-more-activities-card-item").all()
    for i, card in enumerate(more_activities):
        try:
            text = await card.inner_text(timeout=3000)
            html = await card.evaluate("el => el.outerHTML")
            if "icon-check" in html or "SkypeCircleCheck" in html:
                continue
            is_point_mission = text.strip().startswith("5\n") or text.strip().startswith("10\n") or "AddClaim" in html
            if is_point_mission:
                print(f"[Debug] Missão extra encontrada {i+1}. Clicando...")
                await card.click(force=True, timeout=3000)
                await handle_new_pages(context, default_pages_count)
        except Exception as e:
            print(f"[Debug] Erro ao processar card extra {i+1}: {e}")

    print("[Debug] Calculando buscas faltantes...")
    pc_pts, mob_pts, pc_needed, mob_needed = await get_remaining_searches(page)
    return pc_pts, mob_pts, pc_needed, mob_needed

# ==========================================
# FUNÇÕES ANDROID (ADB - DISPOSITIVO FÍSICO)
# ==========================================

ADB_PATH = r"C:\adb\adb.exe"
DEVICE_ID = "RX8T30BGTPW"
LEITURA_META_PONTOS = 45
PONTOS_POR_NOTICIA = 3

def run_adb(command, timeout_sec=25):
    # No Windows, usar lista em vez de string ajuda o subprocess a gerenciar o timeout melhor
    parts = command.split()
    
    # Comandos que nao precisam de ID especifico ou sao globais
    if parts and parts[0] in ['connect', 'devices', 'version', 'start-server', 'kill-server']:
        cmd = [ADB_PATH] + parts
    else:
        cmd = [ADB_PATH] + ["-s", DEVICE_ID] + parts

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors='ignore', timeout=timeout_sec)
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        if "echo" not in command: # Nao poluir o log com timeout de teste
            print(f"[ADB] Timeout de {timeout_sec}s no comando: {command}")
        return ""
    except Exception as e:
        print(f"[ADB] Erro no comando {command}: {e}")
        return ""

def tap(x, y): 
    run_adb(f"shell input tap {x} {y}")
    time.sleep(0.5)
def back(): run_adb("shell input keyevent 4")
def scroll_down(): run_adb("shell input swipe 450 1100 450 200 250")  # rapido
def scroll_up(): run_adb("shell input swipe 450 400 450 1100 250")   # rapido

def get_ui_dump(retries=3):
    if os.path.exists("view.xml"):
        try: os.remove("view.xml")
        except: pass

    for i in range(retries):
        dump_res = run_adb("shell uiautomator dump /sdcard/view.xml", timeout_sec=15)
        if not dump_res:
            print(f"[Debug] ADB nao respondeu ao dump (tentativa {i+1}/{retries})...")
            continue
        run_adb("pull /sdcard/view.xml view.xml", timeout_sec=10)
        if os.path.exists("view.xml") and os.path.getsize("view.xml") > 0:
            with open("view.xml", "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                if "node" in content: return content
        time.sleep(2)
    return ""

def parse_bounds(bounds_str):
    nums = re.findall(r'\d+', bounds_str)
    return [int(n) for n in nums] if len(nums) == 4 else [0,0,0,0]

def is_bing_open():
    return "com.microsoft.bing" in run_adb("shell dumpsys window windows")

def kill_emulator():
    print("[*] Limpando processos...")
    run_adb("shell svc power stayon false")
    os.system("taskkill /F /IM scrcpy.exe /T 2>NUL")
    os.system("taskkill /F /IM adb.exe /T 2>NUL")
    time.sleep(3)

def ensure_emulator_running():
    print(f"[*] Verificando conexão com dispositivo físico ({DEVICE_ID})...")
    
    subprocess.run([ADB_PATH, "start-server"], capture_output=True, timeout=15)
    
    if "." in DEVICE_ID:
        print("[*] Conectando via Wi-Fi...")
        run_adb(f"connect {DEVICE_ID}", timeout_sec=10)
    else:
        print("[*] Conexão via Cabo USB selecionada.")
        
    devices = run_adb("devices", timeout_sec=5)
    
    if DEVICE_ID in devices and "unauthorized" in devices:
        print(f"\n[ERRO CRITICO] O dispositivo {DEVICE_ID} está NAO AUTORIZADO!")
        print("[ACAO NECESSARIA] Olhe para a tela do seu celular e aceite a permissao de Depuracao USB ('Permitir a partir deste computador').")
        return False
        
    if ("device" in devices and DEVICE_ID in devices) or ("192" in devices and "device" in devices):
        print(f"[OK] Dispositivo físico conectado com sucesso! ({DEVICE_ID})")
        
        # Inicia o Scrcpy para manter a tela física apagada durante a automação
        print("[*] Iniciando Scrcpy (Tela Física Apagada)...")
        scrcpy_path = r"C:\Users\super\Documents\Projetos\scrcpy-win64-v3.1\scrcpy.exe"
        try:
            # --power-off-on-close garante que quando o scrcpy fechar, a tela ficará desligada/bloqueada
            subprocess.Popen([scrcpy_path, "--turn-screen-off", "--power-off-on-close"])
            time.sleep(3)
        except Exception as e:
            print(f"[Aviso] Nao foi possivel iniciar o Scrcpy: {e}")

        # Mantém a tela ligada no sistema / economiza bateria
        run_adb("shell svc power stayon true | usb")
        run_adb("shell input keyevent 224") # WAKEUP
        time.sleep(1)
        run_adb("shell input keyevent 82") # MENU (Desbloqueio genérico se sem senha)
        run_adb("shell settings put system screen_brightness 0") # Brilho no zero
        # Limpa possíveis modais abertos na tela
        clear_blocking_modals()
        return True
        
    print("[ERRO] Dispositivo não está respondendo. Verifique a tela dele ou refaça o pareamento.")
    return False



def launch_bing():
    """Inicia o app Bing no dispositivo físico.
    Tenta ate 3 vezes com reconexao ADB entre tentativas.
    """
    for tentativa in range(3):
        if tentativa > 0:
            print(f"[Debug] Reconectando ADB e retentando launch_bing (tentativa {tentativa+1}/3)...")
            run_adb(f"connect {DEVICE_ID}")
            time.sleep(5)

        print("[Debug] Solicitando abertura do Bing...")
        run_adb("shell am start -n com.microsoft.bing/com.microsoft.sapphire.app.main.SapphireMainActivity", timeout_sec=30)
        print("[Debug] Aguardando interface estabilizar...")
        for i in range(12):
            time.sleep(2)
            if is_bing_open():
                print(f"[Debug] Janela do Bing detectada ({i+1}/12).")
                time.sleep(5)
                return True

        print(f"[Debug] Bing nao detectado na tentativa {tentativa+1}/3.")

    print("[ERRO] Nao foi possivel abrir o Bing apos 3 tentativas.")
    return False

def clear_blocking_modals():
    """Fecha rapidamente apenas o popup 'Talvez depois' ou 'Agora não'."""
    xml = get_ui_dump(retries=1)
    if not xml: return
    try:
        root = ET.fromstring(xml)
        for node in root.iter('node'):
            t = node.get('text', '').lower().strip()
            c = node.get('content-desc', '').lower().strip()
            if t in ['talvez depois', 'maybe later', 'agora não', 'not now'] or c in ['talvez depois', 'maybe later', 'agora não', 'not now']:
                b = parse_bounds(node.get('bounds', ''))
                tap((b[0]+b[2])//2, (b[1]+b[3])//2)
                time.sleep(2)
                break
    except: pass

def go_home():
    run_adb("shell input keyevent 3")  # KEYCODE_HOME
    time.sleep(2)
    launch_bing()

def contar_moedas_nao_coletadas(xml, min_y=500):
    """Conta moedas com numero escrito (nao coletadas ainda) no card de check-in semanal.
    
    Card semanal: 7 dias. Dias ja coletados = icone de check dourado (sem texto numerico).
    Dias ainda nao coletados = moeda com valor numerico escrito (ex: '3', '5', '10').
    Retorna a contagem de moedas nao coletadas, ou -1 se nao foi possivel ler.
    """
    if not xml:
        return -1
    try:
        root = ET.fromstring(xml)
        
        # 1. Validação estrita: O card de checkin precisa estar inequivocamente na tela.
        # Buscamos palavras-chave como 'check-in', 'check in' ou dias numéricos na configuração das Recompensas.
        tem_card = False
        for node in root.iter('node'):
            t = (node.get('text') or '').lower().strip()
            c = (node.get('content-desc') or '').lower().strip()
            # Identificadores muito fortes de que estamos na aba de Recompensas/Check-in
            if 'check-in' in t or 'check-in' in c or 'check in' in t or 'check in' in c:
                tem_card = True
                break
            if re.search(r'\b(dia|day)\s*\d\b', t) or re.search(r'\b(dia|day)\s*\d\b', c):
                tem_card = True
                break
                
        if not tem_card:
            print("[Check-in] Nenhum texto indicativo do card de check-in ('Dia X', 'Check-in') encontrado na tela.")
            return 0  # Se não está na tela, assumimos 0 moedas pendentes visíveis
        
        # 2. Contagem das moedas
        count = 0
        for node in root.iter('node'):
            t = node.get('text', '').strip()
            # Moeda nao coletada tem texto numerico curto (valor em pontos)
            if re.match(r'^\d{1,3}$', t):
                val = int(t)
                if 1 <= val <= 200:  # Intervalo tipico de pontos por moeda
                    b = parse_bounds(node.get('bounds', ''))
                    # Filtra por posicao e tamanho da caixa: as moedas sao componentes pequenos e proporcionais
                    w, h = b[2] - b[0], b[3] - b[1]
                    if b[1] >= min_y and w > 0 and h > 0 and w < 160 and h < 160:
                        count += 1
                        
        return count
    except Exception as e:
        print(f"[Check-in] Erro ao parsear XML para contagem: {e}")
        return -1

def return_to_home_top():
    """Toca no icone 'Home/Início' na barra inferior para voltar ao topo instantaneamente."""
    print("[*] Retornando ao topo via ícone Home...")
    
    # Tentativa 1: Localizar dinamicamente no XML
    xml = get_ui_dump(retries=2)
    if xml:
        try:
            root = ET.fromstring(xml)
            for node in root.iter('node'):
                desc = (node.get('content-desc') or '').lower()
                res = (node.get('resource-id') or '').lower()
                text = (node.get('text') or '').lower()
                
                # Critérios de busca para o botão Home
                is_home = any(hid in res for hid in ['navigation_home', 'home_nav', 'tab_home', 'bottom_nav_home']) or \
                          any(htxt in desc for htxt in ['home', 'início', 'inicio']) or \
                          any(htxt in text for htxt in ['home', 'início', 'inicio'])
                
                if is_home:
                    b = parse_bounds(node.get('bounds', ''))
                    # Na barra inferior do S20 FE, o Y inicial costuma ser > 1800
                    if b[1] > 1800:
                        print(f"[OK] Ícone Home detectado em {b}. Clicando...")
                        tap((b[0]+b[2])//2, (b[1]+b[3])//2)
                        time.sleep(1.2)
                        return True
        except: pass
    
    # Tentativa 2: Clique cego na posição padrão do S20 FE caso o XML falhe
    # Geralmente a barra de navegação inferior fica abaixo de Y=2100.
    print("[AVISO] Ícone Home não encontrado no XML. Tentando clique forçado na posição (140, 2280)...")
    tap(140, 2280) 
    time.sleep(1.2)
    return True

def do_daily_checkin():
    """Executa o check-in diario.
    1. Localiza e clica no widget Rewards via XML.
    2. Aguarda a aba Rewards carregar.
    3. Tira screenshot e localiza a palavra 'Check-in' por cor para clicar com precisao.
    """
    print("[Check-in] Iniciando processo de check-in...")
    return_to_home_top()
    time.sleep(3)

    print("[Check-in] Procurando widget do Rewards via XML...")
    rewards_bounds = None
    REWARDS_CARD_IDS = [
        'com.microsoft.bing:id/rewards_widget',
        'com.microsoft.bing:id/sa_hp_reward_card',
        'com.microsoft.bing:id/rewards_card',
    ]
    
    for i in range(3):
        xml = get_ui_dump(retries=1)
        if not xml: continue
        try:
            root = ET.fromstring(xml)
            # Tentativa 1: IDs de widget conhecidos
            for rid in REWARDS_CARD_IDS:
                node = root.find(f".//node[@resource-id='{rid}']")
                if node is not None:
                    rewards_bounds = parse_bounds(node.get('bounds', ''))
                    break
            
            # Tentativa 2: Busca por texto contendo a pontuação (muito seguro, ex: "Rewards 210/210")
            if not rewards_bounds:
                for node in root.iter('node'):
                    t, c = node.get('text', ''), node.get('content-desc', '')
                    if re.search(r'Rewards.*?\d+', t, re.I) or re.search(r'Rewards.*?\d+', c, re.I):
                        rewards_bounds = parse_bounds(node.get('bounds', ''))
                        break

            # Tentativa 3: Busca genérica pela palavra "Rewards" eliminando botões minúsculos
            if not rewards_bounds:
                for node in root.iter('node'):
                    t, c = node.get('text', ''), node.get('content-desc', '')
                    if 'rewards' in t.lower() or 'rewards' in c.lower():
                        b = parse_bounds(node.get('bounds', ''))
                        # Tem que estar abaixo do topo (Y > 300) e ter largura de card (X > 100)
                        if b[1] > 300 and (b[2] - b[0]) > 100:
                            rewards_bounds = b
                            break
        except Exception as e:
            print(f"[Check-in] Erro ao analisar XML: {e}")
            
        if rewards_bounds: break
        time.sleep(2)

    if rewards_bounds:
        cx = (rewards_bounds[0] + rewards_bounds[2]) // 2
        cy = (rewards_bounds[1] + rewards_bounds[3]) // 2
        print(f"[Check-in] Widget Rewards localizado via XML. Clicando em ({cx}, {cy})...")
        tap(cx, cy)
    else:
        print("[Check-in] Falha ao achar Widget no XML. Usando coordenada fixa fallback (258, 1844)...")
        tap(258, 1844)
        
    print("[Check-in] Aguardando ~10 segundos para a WebView do Rewards carregar por completo...")
    time.sleep(10)

    # Tirar SS para achar palavra Check-in
    def take_screenshot_img(filename):
        run_adb(f"shell screencap -p /sdcard/{filename}")
        run_adb(f"pull /sdcard/{filename} {filename}", timeout_sec=10)
        if os.path.exists(filename):
            try:
                return Image.open(filename).convert("RGB")
            except: pass
        return None

    def find_checkin_text(img):
        """Ao inves de procurar texto branco (que confunde com outros banners),
        procura a faixa horizontal de moedas douradas, e retorna a coordenada
        exata da palavra 'Check-in' que fica imediatamente acima delas.
        """
        if img is None: return None
        gold_y = []
        for y in range(800, 2100, 10):
            for x in range(30, 800, 10):
                r, g, b = img.getpixel((x, y))
                # Cor das moedas de check-in (dourado/amarelo)
                if r > 200 and g > 150 and b < 100:
                    gold_y.append(y)
        
        if len(gold_y) > 10:
            gold_y.sort()
            median_y = gold_y[len(gold_y) // 2]
            # Retorna X=250 (meio da palavra Check-in) e o centro exato da barra de moedas
            return (250, median_y - 110, median_y)
        return None

    print("[Check-in] Capturando tela para verificar se o check-in ja foi feito...")
    img_before = take_screenshot_img("checkin_before.png")
    checkin_pos = find_checkin_text(img_before)

    if not checkin_pos:
        print("[Check-in] Nenhuma moeda dourada detectada. Assumindo que o check-in ja foi coletado hoje.")
        back()
        time.sleep(2)
        return True

    cx, cy, coin_y = checkin_pos
    print(f"[Check-in] Moedas detectadas. Iniciando cliques de seguranca em ({cx}, {cy}) e ({500}, {coin_y})...")
    
    # Clique 1: Meio da palavra Check-in
    tap(cx, cy)
    time.sleep(1)
    # Clique 2: Centro exato das moedas (Day 3/4)
    tap(500, coin_y)

    print("[Check-in] Aguardando 12 segundos para processamento...")
    time.sleep(12)

    print("[Check-in] Verificando se o check-in foi bem sucedido (moedas devem sumir)...")
    img_after = take_screenshot_img("checkin_after.png")
    checkin_pos_after = find_checkin_text(img_after)

    if not checkin_pos_after:
        print("[Check-in] SUCESSO! Moedas douradas nao sao mais visiveis (check-in realizado).")
    else:
        print("[Check-in] AVISO: Moedas douradas ainda visiveis. O clique pode ter falhado ou demorado.")

    # Retorna para a Home Principal do Bing
    back()
    time.sleep(3)
    
    # Limpeza de arquivos temporários de imagem
    for f in ["checkin_before.png", "checkin_after.png", "checkin_page.png", "test1.png", "test2.png", "test3.png", "test4.png", "test5.png", "view.xml"]:
        if os.path.exists(f):
            try: os.remove(f)
            except: pass

    print("[Check-in] Procedimento concluido.")
    return True
        




def get_home_points(do_scroll=True):
    """Lê os pontos exibidos na home do Bing. Retorna (pts_atuais, pts_maximos).
    Valida que o valor lido é plausível (> 0 e <= 300) para evitar leituras falsas.
    """
    for _ in range(3):
        xml = get_ui_dump()
        if not xml: continue

        m2 = re.search(r'Rewards.*?(\d+)/(\d+)', xml, re.DOTALL | re.IGNORECASE)
        if m2:
            pts, max_p = int(m2.group(1)), int(m2.group(2))
            if 0 < max_p <= 300:  # sanidade: nunca aceitar max=0 ou absurdo
                return pts, max_p

        try:
            root = ET.fromstring(xml)
            for node in root.iter('node'):
                t = node.get('text', '')
                c = node.get('content-desc', '')
                m = re.match(r'^(\d+)/(\d+)$', t.strip()) or re.match(r'^(\d+)/(\d+)$', c.strip())
                if m:
                    pts, max_p = int(m.group(1)), int(m.group(2))
                    if 0 < max_p <= 300:
                        return pts, max_p
        except: pass

        if do_scroll:
            scroll_up()
            time.sleep(1.5)
    return None, None  # Indica falha de leitura — chamador deve tratar

def force_restart_bing():
    print("[*] Reiniciando Bing para destravar interface...")
    run_adb("shell am force-stop com.microsoft.bing")
    time.sleep(2)
    launch_bing()
    time.sleep(5)

# Termos que identificam o label de anuncio no XML do Bing (Android)
_AD_LABELS = {'anúncio', 'anuncio', 'ad', 'advertisement', 'patrocinado', 'sponsored', 'publicidade'}

def is_ad_card(card_node, root):
    """Retorna True se o card for identificado como anuncio.
    Estrategia:
    1. Varre a subarvore do proprio card buscando o label de anuncio.
    2. Varre os nos irmaos (filhos do pai do card) que estejam proximos ao card.
    """
    def has_ad_label(node):
        for n in node.iter('node'):
            t = (n.get('text') or '').strip().lower()
            c = (n.get('content-desc') or '').strip().lower()
            if t in _AD_LABELS or c in _AD_LABELS:
                return True
            # resource-id com 'ad' ou 'sponsored' (ex: com.microsoft.bing:id/ad_label)
            rid = (n.get('resource-id') or '').lower()
            if 'ad_label' in rid or 'sponsored' in rid or 'advertisement' in rid:
                return True
        return False

    # 1. Checa dentro do proprio card
    if has_ad_label(card_node):
        return True

    # 2. Checa nos irmaos: encontra o pai do card e varre os filhos diretos proximos
    card_bounds = card_node.get('bounds', '')
    for parent in root.iter('node'):
        children = list(parent)
        for idx, child in enumerate(children):
            if child.get('bounds') == card_bounds:
                # Verifica os 3 irmaos seguintes ao card (onde o label 'Anuncio' costuma aparecer)
                for j in range(idx + 1, min(idx + 4, len(children))):
                    if has_ad_label(children[j]):
                        return True
                # Verifica tambem os 2 irmaos anteriores (algumas versoes colocam antes)
                for j in range(max(0, idx - 2), idx):
                    if has_ad_label(children[j]):
                        return True
                return False  # Achou o card no XML, nenhum irmao tinha label
    return False


def read_news_logic(initial_pts, max_pts, news_override=None, read_titles_set=None):
    import math
    read_titles = read_titles_set if read_titles_set is not None else set()
    
    if initial_pts >= max_pts or (news_override is None and (max_pts - initial_pts) <= 0):
        print("[*] Nenhuma noticia necessária ou já concluído.")
        return initial_pts, read_titles

    pts_faltando = news_override * 3 if news_override else max(0, min(max_pts, initial_pts + 30) - initial_pts)
    news_needed = news_override if news_override else math.ceil(pts_faltando / 3)
    
    print(f"[*] Iniciando leitura: {news_needed} noticias (Max 30 tentativas).")
    scroll_down()
    time.sleep(2)

    news_successful = 0
    attempts = 0
    max_attempts = 30
    consecutive_no_find = 0   # tentativas seguidas sem achar noticia nova
    MAX_NO_FIND = 3            # reinicia o Bing apos X misses consecutivos
    current_pts = initial_pts
    # Blacklist residual: apenas termos de UI do Bing (nao noticias)
    UI_BLACKLIST = ['termos de uso', 'política de privacidade', 'entrar', 'feedback']

    while news_successful < news_needed and attempts < max_attempts:
        # Fecha modais ("Talvez depois", etc.) antes de cada tentativa
        clear_blocking_modals()

        xml = get_ui_dump(retries=2)
        if not xml:
            scroll_down(); time.sleep(1.5); continue

        try:
            root = ET.fromstring(xml)
            # Prioridade: cards com resource-id oficial de noticias
            cards = root.findall(".//node[@resource-id='com.microsoft.bing:id/sa_hp_native_list_item_container']")
            # Fallback: pai do titulo oficial
            if not cards:
                cards = root.findall(".//node[@resource-id='com.microsoft.bing:id/sa_hp_native_list_item_title']/..")
        except:
            scroll_down(); continue

        found = False
        for card in cards:
            # --- Detector de anuncio por estrutura XML ---
            if is_ad_card(card, root):
                # Loga apenas uma vez por titulo para nao poluir o terminal
                ad_title_node = card.find(".//node[@resource-id='com.microsoft.bing:id/sa_hp_native_list_item_title']")
                ad_title = (ad_title_node.get('text', '') if ad_title_node is not None else '')[:35]
                safe_ad = ad_title.encode('ascii', errors='replace').decode('ascii')
                print(f"[*] Ignorando anuncio (label detectado): {safe_ad or '(sem titulo)'}")
                if ad_title:
                    read_titles.add(ad_title)  # nao clicar denovo
                continue

            # Busca titulo dentro do card
            title_node = card.find(".//node[@resource-id='com.microsoft.bing:id/sa_hp_native_list_item_title']")
            title = title_node.get('text', '').strip() if title_node is not None else ''

            if not title:
                title = card.get('text', '').strip()

            if not title:
                continue

            if title in read_titles:
                continue

            # Titulo muito curto = botao ou banner (nao e noticia)
            if len(title) < 15:
                continue

            # Blacklist de elementos de UI (nao de assunto)
            if any(w in title.lower() for w in UI_BLACKLIST):
                read_titles.add(title)
                continue

            b = parse_bounds(card.get('bounds', ''))
            if b[1] < 300 or b[3] > 2300: continue
            # Rejeita cards muito finos (banners de anuncio costumam ser baixos)
            if (b[3] - b[1]) < 80:
                continue

            safe_title = title[:40].encode('ascii', errors='replace').decode('ascii')
            print(f"[*] [{news_successful+1}/{news_needed}] (T:{attempts+1}) Abrindo: {safe_title}...")
            tap((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
            read_titles.add(title)

            time.sleep(4)
            # Fecha modal se abriu depois do clique
            clear_blocking_modals()
            scroll_down()
            time.sleep(12)
            back()
            time.sleep(3)
            # Fecha modal se apareceu depois do back
            clear_blocking_modals()

            found = True
            attempts += 1
            break

        if found:
            consecutive_no_find = 0  # reset: achou uma noticia
            # Volta ao topo para ler pontos (Home ja scrolla automaticamente)
            return_to_home_top()
            clear_blocking_modals()  # fecha qualquer popup que apareceu no Home

            new_pts, mx = get_home_points(do_scroll=False)
            if new_pts is not None:
                if new_pts > current_pts:
                    print(f"    -> [SUCESSO] Pontos subiram! {current_pts} -> {new_pts}")
                    news_successful += 1
                    current_pts = new_pts
                else:
                    print(f"    -> [FALHA] Pontos não subiram. (Mantidos em {current_pts})")
            else:
                print(f"    -> [ERRO] Não achou tela de pontos (propaganda travou?). Reiniciando Bing...")
                force_restart_bing()
                clear_blocking_modals()
                time.sleep(3)
                new_pts_retry, _ = get_home_points(do_scroll=False)
                if new_pts_retry is not None:
                    if new_pts_retry > current_pts:
                        print(f"    -> [SUCESSO-RESTART] Pontos subiram! {current_pts} -> {new_pts_retry}")
                        news_successful += 1
                        current_pts = new_pts_retry
                    else:
                        print(f"    -> [FALHA-RESTART] Pontos não subiram. (Mantidos em {current_pts})")
                else:
                    print(f"    -> [AVISO] Ainda não leu pontos. Assumindo sucesso cego.")
                    news_successful += 1
                    current_pts += 3

            # Desce uma vez para sair dos widgets e entrar na lista de noticias
            scroll_down()
            time.sleep(1)
        else:
            consecutive_no_find += 1
            if consecutive_no_find >= MAX_NO_FIND:
                print(f"[*] {MAX_NO_FIND} tentativas sem noticia nova. Reiniciando Bing para atualizar feed...")
                force_restart_bing()
                clear_blocking_modals()
                consecutive_no_find = 0
                # Scroll inicial para entrar na lista de noticias
                scroll_down()
                time.sleep(1.5)
            else:
                scroll_down()
                time.sleep(1.5)

    return current_pts, read_titles

# ==========================================
# GESTÃO DE RELATÓRIO E AGENDAMENTO
# ==========================================

def send_telegram_msg(text):
    if not TELEGRAM_TOKEN or TELEGRAM_CHAT_ID == "PENDENTE": return False
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=15)
        return True
    except: return False

def format_report_line(pts_start, pts_end, max_pts):
    ganhos = pts_end - pts_start
    if pts_start >= max_pts:
        return "✅ Já concluído"
    elif pts_end >= max_pts:
        return f"✅ Concluído (+{ganhos} pts)"
    else:
        if ganhos > 0:
            return f"❌ Incompleto (+{ganhos} pts, fez {pts_end}/{max_pts})"
        else:
            return f"❌ Falhou (0 pts ganhos, marcando {pts_end}/{max_pts})"

def run_bing_app_automation():
    stats = {"checkin_report": "❌ Falhou", "news_report": "❌ Falhou"}

    if not ensure_emulator_running():
        return stats

    if not launch_bing():
        print("[ERRO] Não foi possível abrir o Bing.")
        return stats

    print("[*] Aguardando estabilidade do Bing...")
    time.sleep(6)
    clear_blocking_modals()

    try:
        if do_daily_checkin():
            stats["checkin_report"] = "✅ Concluido"
        else:
            stats["checkin_report"] = "❌ Nao detectado"
    except Exception as e:
        print(f"[Erro] Falha no Check-in: {e}")

    print("[*] Reiniciando o app Bing para leitura limpa antes das noticias...")
    force_restart_bing()
    clear_blocking_modals()

    pts_iniciais, max_pts = get_home_points(do_scroll=True)
    if pts_iniciais is None:
        pts_iniciais, max_pts = 0, 210
    print(f"[*] Pontos antes das noticias: {pts_iniciais}/{max_pts}")

    pts_finais, _ = read_news_logic(pts_iniciais, max_pts)
    
    pontos_ganhos = pts_finais - pts_iniciais
    pts_alvo_final = min(max_pts, pts_iniciais + 30)

    if pts_iniciais >= max_pts:
        stats["news_report"] = "OK Ja concluido antes de comecar"
    elif pts_finais >= pts_alvo_final:
        stats["news_report"] = f"OK Concluido (+{pontos_ganhos} pts)"
    elif pontos_ganhos >= 30:
        stats["news_report"] = f"OK Concluido (+{pontos_ganhos} pts)"
    else:
        stats["news_report"] = (
            f"INCOMPLETO (+{pontos_ganhos} pts, "
            f"Atual: {pts_finais}/{max_pts})"
        )

    run_adb("shell am force-stop com.microsoft.bing")
    stats["pts_final"] = pts_finais
    stats["pts_max"] = max_pts
    return stats

async def run_full_automation():
    os.system("taskkill /F /IM msedge.exe /T 2>NUL")
    relatorio = {"hora": datetime.now().strftime("%H:%M"), "diario": "✅ Concluido",
                 "pc": "❌ Falhou", "mob": "❌ Falhou", "checkin": "❌ Falhou", "news": "❌ Falhou",
                 "pts_final": 0, "pts_max": 210}

    async with async_playwright() as p:
        try:
            pc_pts_1 = pc_pts_2 = mob_pts_1 = mob_pts_2 = 0
            # Loop Local PC (Max 5x)
            for attempt in range(5):
                print(f"[Web] Tentativa PC {attempt+1}/5")
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data"),
                    channel="msedge", headless=False, no_viewport=True, args=["--start-maximized"]
                )
                pc_pts_tmp, mob_pts_tmp, pc_needed, mob_needed = await do_daily_sets(context, len(context.pages))
                
                if attempt == 0:
                    pc_pts_1, mob_pts_1 = pc_pts_tmp, mob_pts_tmp
                    
                if pc_needed > 0:
                    await perform_searches(context, pc_needed, "PC")
                    pc_pts_2, mob_pts_2, p_needed_f, _ = await get_remaining_searches(context.pages[0])
                    await context.close()
                    if p_needed_f <= 0: break
                else:
                    pc_pts_2, mob_pts_2 = pc_pts_tmp, mob_pts_tmp
                    await context.close()
                    break
                    
            relatorio["pc"] = format_report_line(pc_pts_1, pc_pts_2, 90)
            await asyncio.sleep(2)

            mob_pts_3 = mob_pts_2
            mob_needed_2 = max(0, (60 - mob_pts_2) // 3)
            # Loop Local Edge Mobile (Max 5x)
            for attempt in range(5):
                if mob_needed_2 <= 0: break
                print(f"[Web] Tentativa Edge Mobile {attempt+1}/5")
                mobile_device = p.devices['Pixel 5']
                mobile_device.pop("default_browser_type", None)
                mob_context = await p.chromium.launch_persistent_context(
                    user_data_dir=os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data"),
                    channel="msedge", headless=False, **mobile_device
                )
                await perform_searches(mob_context, mob_needed_2, "Mobile")
                await mob_context.close()
                await asyncio.sleep(2)

                verify_context = await p.chromium.launch_persistent_context(
                    user_data_dir=os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data"),
                    channel="msedge", headless=False, no_viewport=True, args=["--start-maximized"]
                )
                verify_page = verify_context.pages[0] if verify_context.pages else await verify_context.new_page()
                _, mob_pts_3, _, mob_needed_2 = await get_remaining_searches(verify_page)
                await verify_context.close()
                
            relatorio["mob"] = format_report_line(mob_pts_2, mob_pts_3, 60)

        except Exception as e:
            print(f"Erro Web: {e}")

    app = run_bing_app_automation()
    relatorio["checkin"], relatorio["news"] = app["checkin_report"], app["news_report"]
    relatorio["pts_final"] = app.get("pts_final", 0)
    relatorio["pts_max"] = app.get("pts_max", 210)

    kill_emulator()

    return relatorio

async def main():
    print(f"\n=== INICIANDO EXECUCAO UNICA COM RETENTATIVAS LOCAIS ===")
    relatorio = await run_full_automation()

    if relatorio["pts_final"] >= relatorio["pts_max"] and relatorio["pts_max"] > 0:
        print(f"[*] Sucesso total atingido: {relatorio['pts_final']}/{relatorio['pts_max']}")
    else:
        print(f"[!] Pontos incompletos ou falha nas verificacoes: {relatorio['pts_final']}/{relatorio['pts_max']}")

    msg = (f"RELATORIO BING AUTO - {relatorio['hora']}\n\n"
           f"Daily Set: {relatorio['diario']}\n"
           f"Buscas PC: {relatorio['pc']}\n"
           f"Buscas Mob: {relatorio['mob']}\n"
           f"Check-in: {relatorio['checkin']}\n"
           f"Noticias: {relatorio['news']}\n"
           f"Pontuacao Final: {relatorio['pts_final']}/{relatorio['pts_max']}\n\n"
           f"Status: {'Concluido' if relatorio['pts_final'] >= relatorio['pts_max'] else 'Incompleto'}")

    # Mensagem Telegram com emojis (separada do print no terminal Windows)
    msg_telegram = (f"\U0001f680 *RELATORIO BING AUTO - {relatorio['hora']}*\n\n"
                    f"\U0001f4c5 *Daily Set:* {relatorio['diario']}\n"
                    f"\U0001f4bb *Buscas PC:* {relatorio['pc']}\n"
                    f"\U0001f4f1 *Buscas Mob:* {relatorio['mob']}\n"
                    f"\U0001fa99 *Check-in:* {relatorio['checkin']}\n"
                    f"\U0001f4f0 *Noticias:* {relatorio['news']}\n"
                    f"\U0001f3c6 *Pontuacao Final:* {relatorio['pts_final']}/{relatorio['pts_max']}\n\n"
                    f"\U0001f3af _Status: {'Concluido' if relatorio['pts_final'] >= relatorio['pts_max'] else 'Incompleto'}_")

    # Print seguro para terminais Windows (com fallback caso haja emojis/caracteres nao suportados)
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))
    
    send_telegram_msg(msg_telegram)
    os.system("taskkill /F /IM msedge.exe /T 2>NUL")
    kill_emulator()

if __name__ == "__main__":
    asyncio.run(main())