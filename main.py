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
    # Aguarda até 8 segundos para ver se uma nova página/aba se abre
    for _ in range(8):
        if len(context.pages) > default_pages_count:
            break
        await asyncio.sleep(1)
        
    if len(context.pages) > default_pages_count:
        new_page = context.pages[-1]
        print(f"[Debug] Nova aba detectada: {new_page.url[:50]}. Interagindo...")
        try:
            # Espera carregar um pouco
            await new_page.wait_for_load_state("domcontentloaded", timeout=5000)
        except: pass
        try:
            # Simula scroll
            await new_page.evaluate("window.scrollBy(0, window.innerHeight / 2)")
            await human_delay(2000, 4000)
            await new_page.evaluate("window.scrollBy(0, -window.innerHeight / 4)")
            await human_delay(1000, 2000)
        except: pass
        try:
            await new_page.close()
            print("[Debug] Nova aba fechada.")
        except: pass

async def claim_points_if_available(page):
    print("[Debug] Verificando pontos para reivindicar...")
    pts = 0
    try:
        card = page.locator("button").filter(has_text="Pronto para reivindicar").last
        if await card.count() > 0:
            text = await card.text_content()
            text_clean = " ".join(text.split())
            print(f"[Debug] Texto do card de reivindicar: '{text_clean}'")
            match = re.search(r'Pronto para reivindicar\s*(?:\|\s*)?(\d+)', text_clean, re.IGNORECASE)
            if match:
                pts = int(match.group(1))
                print(f"[Debug] Encontrado via card específico: {pts} pontos.")
            else:
                digits = re.findall(r'\d+', text_clean)
                if digits:
                    pts = int(digits[0])
        else:
            # Fallback para busca textual geral
            body_text = await page.inner_text("body", timeout=5000)
            match = re.search(r'Pronto para reivindicar\s*(?:\|\s*)?(\d+)', body_text, re.IGNORECASE)
            if match:
                pts = int(match.group(1))
    except Exception as e:
        print(f"[Erro] Falha ao verificar pontos para reivindicar: {e}")
        
    if pts == 0:
        print("[Debug] Não há pontos para reivindicar hoje (pontos = 0 ou não encontrados).")
        return "não há pontos para reivindicar hoje", 0
        
    print(f"[Debug] Reivindicando {pts} pontos...")
    try:
        clicked = False
        card = page.locator("button").filter(has_text="Pronto para reivindicar").first
        if await card.count() > 0:
            print("[Debug] Clicando no card de reivindicar...")
            await card.click(timeout=5000)
            clicked = True
        else:
            reclaim_button_selectors = [
                "button:has-text('Reivindicar')",
                "a:has-text('Reivindicar')",
                "button:has-text('reivindicar')",
                "a:has-text('reivindicar')",
            ]
            for selector in reclaim_button_selectors:
                loc = page.locator(selector)
                if await loc.count() > 0:
                    print(f"[Debug] Clicando no botão de reivindicação fallback ({selector})...")
                    await loc.first.click(timeout=5000)
                    clicked = True
                    break
                    
        if not clicked:
            print("[Erro] Botão de reivindicação não localizado.")
            return "falha ao reivindicar pontos", 0

        await human_delay(3000, 5000)
        
        panel_button_selectors = [
            "button:has-text('reivindicar pontos')",
            "a:has-text('reivindicar pontos')",
            "button:has-text('Reivindicar pontos')",
            "a:has-text('Reivindicar pontos')",
            "button:has-text('reivindicar')",
            "a:has-text('reivindicar')",
            "[aria-label*='reivindicar pontos']",
            "[aria-label*='Reivindicar pontos']"
        ]
        
        clicked_panel = False
        for selector in panel_button_selectors:
            loc = page.locator(selector)
            for idx in range(await loc.count()):
                el = loc.nth(idx)
                if await el.is_visible():
                    try:
                        await el.scroll_into_view_if_needed()
                    except: pass
                    print(f"[Debug] Clicando no botão do painel lateral ({selector})...")
                    await el.click(timeout=5000)
                    clicked_panel = True
                    break
            if clicked_panel:
                break
                
        if not clicked_panel:
            loc = page.get_by_text("reivindicar pontos", exact=False)
            if await loc.count() > 0:
                await loc.first.scroll_into_view_if_needed()
                await loc.first.click(timeout=5000)
                clicked_panel = True
                
        if clicked_panel:
            await human_delay(3000, 5000)
            print(f"[SUCESSO] Pontos reivindicados com sucesso: {pts} pontos.")
            return f"reivindicados (+{pts} pts)", pts
        else:
            print("[Erro] Botão final 'reivindicar pontos' não localizado no painel lateral.")
            return "falha ao reivindicar pontos", 0
            
    except Exception as e:
        print(f"[Erro] Falha no fluxo de reivindicar pontos: {e}")
        return "falha ao reivindicar pontos", 0

async def get_daily_set_cards(page):
    print("[Debug] Procurando seção 'definido diariamente'...")
    daily_set_titles = ["Definido diariamente", "Daily set", "Daily Set", "definido diariamente"]
    
    xpath_daily = " | ".join([f"//div[contains(@class, 'react-aria-Disclosure')][descendant::*[contains(text(), '{t}')]]" for t in daily_set_titles])
    disclosure = page.locator(xpath_daily)
    
    cards_found = []
    if await disclosure.count() > 0:
        panel = disclosure.locator("div.react-aria-DisclosurePanel")
        all_elements = await panel.locator("a, button, [role='button']").all()
        for el in all_elements:
            text = await el.text_content()
            text_clean = " ".join(text.split())
            if len(text_clean) > 15:
                cards_found.append(el)
    
    if not cards_found:
        print("[Debug] Busca estruturada não localizou os cards. Usando busca de fallback...")
        try:
            candidates = await page.locator("a, button, [role='button'], div.card, div.cursor-pointer, div[class*='cursor-pointer']").all()
            for cand in candidates:
                if await cand.is_visible():
                    text = await cand.text_content()
                    if text and any(x in text for x in ["Concluído", "Concluido", "10", "30", "50"]):
                        cards_found.append(cand)
        except Exception as e:
            print(f"[Debug] Erro no fallback global: {e}")

    unique_cards = []
    seen_boxes = []
    for card in cards_found:
        try:
            text = await card.text_content()
            if not text:
                continue
            box = await card.bounding_box()
            if box:
                cx, cy = box['x'] + box['width']/2, box['y'] + box['height']/2
                if box['width'] == 0 or box['height'] == 0: continue
                duplicated = False
                for sx, sy in seen_boxes:
                    if abs(cx - sx) < 15 and abs(cy - sy) < 15:
                        duplicated = True
                        break
                if not duplicated:
                    unique_cards.append(card)
                    seen_boxes.append((cx, cy))
        except: pass
            
    print(f"[Debug] Encontrados {len(unique_cards)} cards únicos para o conjunto diário.")
    return unique_cards

async def is_card_completed(card):
    try:
        text = await card.text_content()
        # 1. Se o texto contiver palavras de conclusão
        if any(indicator in text.lower() for indicator in ["concluído", "concluido", "completed", "checked"]):
            return True
            
        # 2. Se o HTML contiver indicadores de conclusão
        html = await card.evaluate("el => el.outerHTML")
        if any(indicator in html.lower() for indicator in ["icon-check", "skypecirclecheck", "completed", "concluido", "concluído", "checked"]):
            return True
        if "check" in html.lower() and "svg" in html.lower():
            return True
            
        return False
    except:
        return False

async def run_daily_sets_workflow(context, default_pages_count):
    print("\n--- INICIANDO ETAPA 2: CONJUNTO DIÁRIO ---")
    page = context.pages[0] if context.pages else await context.new_page()
    url = "https://rewards.bing.com/dashboard"
    
    for attempt in range(3):
        print(f"[Daily Set] Tentativa {attempt+1}/3 de conclusão...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await human_delay(3000, 5000)
        except Exception as e:
            print(f"[Daily Set] Erro ao navegar para dashboard: {e}")
            continue
            
        try:
            close_btn = page.locator("button.ms-Dialog-button--close, button[aria-label='Fechar'], button#modal-host-close, button#bnp_btn_accept")
            if await close_btn.count() > 0:
                await close_btn.first.click(timeout=3000)
                await human_delay(1000, 2000)
        except: pass

        cards = await get_daily_set_cards(page)
        if not cards:
            print("[Daily Set] Nenhum card do conjunto diário foi localizado.")
            continue
            
        pending_cards = []
        for card in cards:
            if not await is_card_completed(card):
                pending_cards.append(card)
                
        print(f"[Daily Set] Dos {len(cards)} cards localizados, {len(pending_cards)} estão pendentes.")
        
        if len(pending_cards) == 0:
            print("[SUCESSO] Todos os cards do conjunto diário já estão concluídos!")
            return "Concluído (+30 pts)", 30
            
        for idx, card in enumerate(pending_cards):
            try:
                txt = await card.inner_text()
                txt_safe = txt.replace("\n", " ").strip()[:40].encode('ascii', errors='replace').decode('ascii')
                print(f"[Daily Set] Clicando no card pendente: '{txt_safe}'")
                await card.click(force=True, timeout=5000)
                await handle_new_pages(context, default_pages_count)
                await human_delay(2000, 4000)
            except Exception as e:
                print(f"[Daily Set] Erro ao processar card: {e}")
                
        await human_delay(3000, 5000)
        
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await human_delay(3000, 5000)
        cards = await get_daily_set_cards(page)
        pending_count = 0
        for card in cards:
            if not await is_card_completed(card):
                pending_count += 1
        if pending_count == 0 and len(cards) >= 3:
            return "Concluído (+30 pts)", 30
    except: pass
        
    return "Falhou/Incompleto", 0

async def perform_searches(context, count, device_name="PC"):
    if count <= 0: return
    page = context.pages[0] if context.pages else await context.new_page()
    for i in range(count):
        term_raw = get_random_search_term()
        term = term_raw.encode('ascii', 'ignore').decode('ascii')
        print(f"[{device_name}] Pesquisa {i+1}/{count}: '{term}'")
        try:
            import urllib.parse
            search_url = f"https://www.bing.com/search?q={urllib.parse.quote(term)}&form=CHROMN"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
            await human_delay(1500, 3000)
            try:
                await page.evaluate(f"window.scrollBy(0, {random.randint(300, 700)})")
                await human_delay(1000, 2000)
                await page.evaluate(f"window.scrollBy(0, {random.randint(100, 400)})")
            except: pass
            await human_delay(7000, 10000)
        except Exception as e: 
            print(f"Erro pesquisa: {e}")

async def check_and_perform_searches(context):
    print("\n--- INICIANDO ETAPA 3: PESQUISAS (WEB 60 PONTOS) ---")
    page = context.pages[0] if context.pages else await context.new_page()
    url = "https://rewards.bing.com/earn"
    
    current_pts = 0
    max_pts = 60
    
    for attempt in range(3):
        print(f"[Pesquisas] Tentativa {attempt+1}/3 de verificação/pesquisa...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await human_delay(3000, 5000)
        except Exception as e:
            print(f"[Pesquisas] Erro ao navegar para a página /earn: {e}")
            continue
            
        print("[Pesquisas] Procurando botão de 'Detalhamento de pontos'...")
        btn = page.locator("button").filter(has_text="Detalhamento de pontos")
        clicked_today_points = False
        if await btn.count() > 0:
            print("[Pesquisas] Clicando no botão...")
            try:
                await btn.first.click(timeout=5000)
                await human_delay(3000, 5000)
                clicked_today_points = True
            except Exception as e:
                print(f"[Pesquisas] Falha ao clicar no botão: {e}")
        
        if not clicked_today_points:
            print("[Pesquisas] Não foi possível clicar no card 'Detalhamento de pontos'. Fazendo 20 pesquisas cegas...")
            await perform_searches(context, 20, "PC")
            return "Concluído (Buscas feitas às cegas)", 60
            
        print("[Pesquisas] Lendo pontos da barra lateral...")
        found_pts = False
        try:
            row_locator = page.locator("div").filter(has_text="Pesquisa do Bing").filter(has_text="/60")
            count = await row_locator.count()
            if count > 0:
                text = await row_locator.last.text_content()
                text_clean = " ".join(text.split())
                print(f"[Pesquisas] Texto do contêiner de pesquisa: '{text_clean}'")
                match = re.search(r'(\d+)\s*/\s*60', text_clean)
                if match:
                    current_pts = int(match.group(1))
                    found_pts = True
                    print(f"[Pesquisas] Pontos atuais detectados: {current_pts}/60")
            
            if not found_pts:
                row_locator_fallback = page.locator("div").filter(has_text="Pesquisa do Bing")
                fb_count = await row_locator_fallback.count()
                if fb_count > 0:
                    text = await row_locator_fallback.last.text_content()
                    text_clean = " ".join(text.split())
                    print(f"[Pesquisas] Fallback - Texto do contêiner de pesquisa: '{text_clean}'")
                    match = re.search(r'(\d+)\s*/\s*(\d+)', text_clean)
                    if match:
                        current_pts = int(match.group(1))
                        max_pts = int(match.group(2))
                        found_pts = True
                        print(f"[Pesquisas] Pontos atuais (Fallback): {current_pts}/{max_pts}")
        except Exception as e:
            print(f"[Pesquisas] Erro ao ler barra lateral: {e}")
            
        if not found_pts:
            print("[Pesquisas] Não foi possível ler a pontuação. Assumindo 0/60 e continuando...")
            current_pts = 0
            
        if current_pts >= max_pts:
            print(f"[SUCESSO] Pesquisas web concluídas ({current_pts}/{max_pts})!")
            return f"Concluído ({current_pts}/{max_pts})", current_pts
            
        searches_needed = (max_pts - current_pts) // 3
        if searches_needed <= 0:
            searches_needed = 20
            
        print(f"[Pesquisas] Faltam {max_pts - current_pts} pontos. Iniciando {searches_needed} pesquisas...")
        await perform_searches(context, searches_needed, "PC")
        await human_delay(3000, 5000)
        
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await human_delay(3000, 5000)
        btn = page.locator("button").filter(has_text="Detalhamento de pontos")
        if await btn.count() > 0:
            await btn.first.click(timeout=5000)
            await human_delay(3000, 5000)
            row_locator = page.locator("div").filter(has_text="Pesquisa do Bing").filter(has_text="/60")
            if await row_locator.count() > 0:
                text = await row_locator.last.text_content()
                text_clean = " ".join(text.split())
                match = re.search(r'(\d+)\s*/\s*60', text_clean)
                if match:
                    current_pts = int(match.group(1))
                    if current_pts >= max_pts:
                        return f"Concluído ({current_pts}/60)", 60
                    else:
                        return f"Incompleto ({current_pts}/60)", current_pts
    except: pass
        
    return f"Incompleto ({current_pts}/{max_pts})", current_pts

async def get_keep_earning_progress(page):
    print("[Debug] Procurando progresso de 'continuar ganhando'...")
    earn_titles = ["Continuar ganhando", "Keep earning"]
    xpath_earn = " | ".join([f"//div[contains(@class, 'react-aria-Disclosure')][descendant::*[contains(text(), '{t}')]]" for t in earn_titles])
    disclosure = page.locator(xpath_earn)
    
    if await disclosure.count() > 0:
        text = await disclosure.locator("div.rounded-cornerCardDefault, [class*='rounded-cornerCardDefault']").first.text_content()
        text_clean = " ".join(text.split())
        match = re.search(r'(\d+)\s*/\s*(\d+)', text_clean)
        if match:
            earned = int(match.group(1))
            total = int(match.group(2))
            print(f"[Debug] Progresso extra encontrado: {earned}/{total}")
            return earned, total, disclosure
    return None, None, None

async def get_keep_earning_cards(container, page):
    cards_found = []
    if container:
        try:
            panel = container.locator("div.react-aria-DisclosurePanel")
            all_elements = await panel.locator("a, button, [role='button']").all()
            for el in all_elements:
                text = await el.text_content()
                text_clean = " ".join(text.split())
                if len(text_clean) > 15:
                    cards_found.append(el)
        except Exception as e:
            print(f"[Debug] Erro ao obter cards do Continuar Ganhando: {e}")
            
    unique_cards = []
    seen_boxes = []
    for card in cards_found:
        try:
            text = await card.text_content()
            if not text:
                continue
            box = await card.bounding_box()
            if box:
                cx, cy = box['x'] + box['width']/2, box['y'] + box['height']/2
                if box['width'] == 0 or box['height'] == 0: continue
                duplicated = False
                for sx, sy in seen_boxes:
                    if abs(cx - sx) < 15 and abs(cy - sy) < 15:
                        duplicated = True
                        break
                if not duplicated:
                    unique_cards.append(card)
                    seen_boxes.append((cx, cy))
        except: pass
        
    return unique_cards

async def do_keep_earning(context, default_pages_count):
    print("\n--- INICIANDO ETAPA 4: CONTINUAR GANHANDO ---")
    page = context.pages[0] if context.pages else await context.new_page()
    url = "https://rewards.bing.com/earn"
    
    for attempt in range(3):
        print(f"[Extras] Tentativa {attempt+1}/3 de conclusão...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await human_delay(3000, 5000)
        except Exception as e:
            print(f"[Extras] Erro ao navegar para a página earn: {e}")
            continue
            
        earned, total, container = await get_keep_earning_progress(page)
        if earned is None or total is None:
            print("[Extras] Não foi possível ler o progresso. Procurando cards de forma genérica...")
            loc = page.get_by_text("continuar ganhando", exact=False)
            if await loc.count() > 0:
                container = loc.first.locator("xpath=..").locator("xpath=..")
                earned, total = 0, 45
            else:
                print("[Extras] Seção não localizada na página.")
                return "Não localizado", 0
                
        if earned >= total:
            print(f"[SUCESSO] Pontos extras já concluídos! ({earned}/{total})")
            return f"Concluído ({earned}/{total})", earned
            
        cards = await get_keep_earning_cards(container, page)
        print(f"[Extras] Encontrados {len(cards)} cards extras na seção.")
        
        pending_cards = []
        for card in cards:
            if not await is_card_completed(card):
                pending_cards.append(card)
                
        print(f"[Extras] Cards pendentes: {len(pending_cards)}")
        if len(pending_cards) == 0:
            print(f"[SUCESSO] Todos os cards extras disponíveis já estão concluídos! ({earned}/{total})")
            return f"Concluído ({earned}/{total})", earned
            
        for idx, card in enumerate(pending_cards):
            try:
                txt = await card.inner_text()
                txt_safe = txt.replace("\n", " ").strip()[:40].encode('ascii', errors='replace').decode('ascii')
                print(f"[Extras] Clicando no card extra pendente {idx+1}/{len(pending_cards)}: '{txt_safe}'")
                await card.click(force=True, timeout=5000)
                await handle_new_pages(context, default_pages_count)
                await human_delay(2000, 4000)
            except Exception as e:
                print(f"[Extras] Erro ao processar card: {e}")
                
        await human_delay(3000, 5000)
        
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await human_delay(3000, 5000)
        earned, total, _ = await get_keep_earning_progress(page)
        if earned is not None:
            if earned >= total:
                return f"Concluído ({earned}/{total})", earned
            else:
                return f"Incompleto ({earned}/{total})", earned
    except: pass
    
    return "Falhou/Incompleto", 0

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
    Usa force-stop antes para garantir que o app abra limpo na Home.
    """
    for tentativa in range(3):
        if tentativa > 0:
            print(f"[Debug] Reconectando ADB e retentando launch_bing (tentativa {tentativa+1}/3)...")
            run_adb(f"connect {DEVICE_ID}")
            time.sleep(5)

        # Fecha o Bing se estiver aberto para garantir estado limpo
        print("[Debug] Fechando Bing (force-stop) para abrir limpo...")
        run_adb("shell am force-stop com.microsoft.bing", timeout_sec=10)
        time.sleep(2)

        print("[Debug] Solicitando abertura do Bing...")
        # Usa a intent MAIN/LAUNCHER ao inves de Activity direta
        # Isso garante que o app abre na Home e nao numa sub-Activity de pesquisa
        run_adb("shell am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n com.microsoft.bing/com.microsoft.sapphire.app.main.SapphireMainActivity", timeout_sec=30)
        print("[Debug] Aguardando interface estabilizar...")
        for i in range(12):
            time.sleep(2)
            if is_bing_open():
                print(f"[Debug] Janela do Bing detectada ({i+1}/12).")
                # Aguarda tempo suficiente para o app carregar a Home completamente
                # (10s evita que interacoes prematuras cliquem na barra de pesquisa)
                print("[Debug] Aguardando 10s para Home carregar completamente...")
                time.sleep(10)
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
    """Toca no icone 'Home/Início' na barra inferior para voltar ao topo instantaneamente.
    Se falhar, faz scroll up 3 vezes para subir o feed com segurança.
    CUIDADO: Evita clicar em campos de pesquisa (EditText) ou elementos não-navegação.
    """
    print("[*] Retornando ao topo via ícone Home...")
    
    # Classes de UI que NÃO são botões de navegação (campo de pesquisa, etc.)
    _SKIP_CLASSES = ['edittext', 'autocompletextview', 'searchview', 'textview']
    
    # Tentativa 1: Localizar dinamicamente no XML
    xml = get_ui_dump(retries=2)
    if xml:
        try:
            root = ET.fromstring(xml)
            best_candidate = None
            best_priority = -1
            
            for node in root.iter('node'):
                desc = (node.get('content-desc') or '').lower()
                res = (node.get('resource-id') or '').lower()
                text = (node.get('text') or '').lower()
                cls = (node.get('class') or '').lower()
                
                # PULAR campos de texto/pesquisa — clicar neles abre a pesquisa do Bing!
                if any(skip in cls for skip in _SKIP_CLASSES):
                    if 'home' in desc or 'home' in text or 'início' in desc:
                        print(f"[Debug] Ignorando elemento tipo '{cls}' com texto home (seria campo de pesquisa)")
                    continue
                
                # PULAR elementos que contenham termos de pesquisa no resource-id
                if any(sid in res for sid in ['search', 'pesquis', 'query', 'omnibox', 'url_bar']):
                    print(f"[Debug] Ignorando elemento de pesquisa: {res}")
                    continue
                
                b = parse_bounds(node.get('bounds', ''))
                # Na barra inferior do S20 FE, o Y inicial costuma ser > 1800
                if b[1] <= 1800:
                    continue
                
                # Prioridade 1 (alta): resource-id específico de navegação
                if any(hid in res for hid in ['navigation_home', 'home_nav', 'tab_home', 'bottom_nav_home', 'bottom_bar']):
                    if best_priority < 3:
                        best_candidate = b
                        best_priority = 3
                        continue
                
                # Prioridade 2 (média): content-desc contém 'home/início' E é um ImageView/Button
                if any(htxt in desc for htxt in ['home', 'início', 'inicio']):
                    if any(ok_cls in cls for ok_cls in ['imageview', 'imagebutton', 'button', 'framelayout', 'linearlayout', 'bottomnavigation']):
                        if best_priority < 2:
                            best_candidate = b
                            best_priority = 2
                            continue
                
                # Prioridade 3 (baixa): text contém 'home/início' com classe aceitável
                if any(htxt in text for htxt in ['home', 'início', 'inicio']):
                    if any(ok_cls in cls for ok_cls in ['imageview', 'imagebutton', 'button', 'tab']):
                        if best_priority < 1:
                            best_candidate = b
                            best_priority = 1
            
            if best_candidate:
                b = best_candidate
                print(f"[OK] Ícone Home detectado em {b} (prioridade {best_priority}). Clicando...")
                tap((b[0]+b[2])//2, (b[1]+b[3])//2)
                time.sleep(1.5)
                return True
        except Exception as e:
            print(f"[Debug] Erro ao buscar ícone Home no XML: {e}")
    
    # Tentativa 2: Fallback com scrolls para cima se o XML/Clique falhar
    print("[AVISO] Ícone Home não encontrado ou clique falhou. Executando scrolls para subir ao topo...")
    for _ in range(3):
        scroll_up()
        time.sleep(0.8)
    return False

def find_rewards_widget_bounds(xml):
    """Localiza o bounding box do card do Rewards de maneira unificada."""
    if not xml:
        return None
    REWARDS_CARD_IDS = [
        'com.microsoft.bing:id/rewards_widget',
        'com.microsoft.bing:id/sa_hp_reward_card',
        'com.microsoft.bing:id/rewards_card',
    ]
    try:
        root = ET.fromstring(xml)
        # Tentativa 1: IDs de widget conhecidos
        for rid in REWARDS_CARD_IDS:
            node = root.find(f".//node[@resource-id='{rid}']")
            if node is not None:
                bounds = parse_bounds(node.get('bounds', ''))
                if bounds[2] - bounds[0] > 100:
                    return bounds
        
        # Tentativa 2: Busca por texto contendo a pontuação (ex: "Rewards 210/210")
        for node in root.iter('node'):
            t, c = node.get('text', ''), node.get('content-desc', '')
            if re.search(r'Rewards.*?\d+', t, re.I) or re.search(r'Rewards.*?\d+', c, re.I):
                bounds = parse_bounds(node.get('bounds', ''))
                if bounds[2] - bounds[0] > 100:
                    return bounds

        # Tentativa 3: Busca genérica pela palavra "Rewards" eliminando botões minúsculos
        for node in root.iter('node'):
            t, c = node.get('text', ''), node.get('content-desc', '')
            if 'rewards' in t.lower() or 'rewards' in c.lower():
                b = parse_bounds(node.get('bounds', ''))
                # Tem que estar abaixo do topo (Y > 300) e ter largura de card (X > 100)
                if b[1] > 300 and (b[2] - b[0]) > 100:
                    return b
    except Exception as e:
        print(f"[Debug] Erro ao analisar XML buscando Rewards: {e}")
    return None

def ensure_bing_home_and_rewards_visible(max_retries=3):
    """Garante que o app está na home e com o card de Rewards visível.
    Tenta fechar modais, ir para o topo e reiniciar o Bing se falhar.
    """
    for att in range(max_retries):
        if att > 0:
            print(f"[Home Check] Widget não detectado. Reiniciando Bing (tentativa {att}/{max_retries - 1})...")
            force_restart_bing()
            
        clear_blocking_modals()
        return_to_home_top()
        
        xml = get_ui_dump(retries=2)
        bounds = find_rewards_widget_bounds(xml)
        if bounds:
            print(f"[Home Check] Widget Rewards detectado com sucesso em {bounds}.")
            return bounds
            
        print("[Home Check] Widget Rewards não foi encontrado.")
        time.sleep(2)
        
    print("[Home Check] FALHA CRÍTICA: Widget do Rewards não foi detectado após as reinicializações.")
    return None

def do_daily_checkin():
    """Executa o check-in diario.
    1. Garante que está na Home e localiza o widget do Rewards.
    2. Clica no widget.
    3. Aguarda a aba Rewards carregar.
    4. Tira screenshot e localiza a palavra 'Check-in' por cor para clicar com precisao.
    """
    print("[Check-in] Iniciando processo de check-in...")
    
    rewards_bounds = ensure_bing_home_and_rewards_visible(max_retries=3)
    if not rewards_bounds:
        print("[Check-in] ABORTADO: Não foi possível assegurar a visibilidade do widget do Rewards.")
        return False

    cx = (rewards_bounds[0] + rewards_bounds[2]) // 2
    cy = (rewards_bounds[1] + rewards_bounds[3]) // 2
    print(f"[Check-in] Widget Rewards localizado. Clicando em ({cx}, {cy})...")
    tap(cx, cy)
        
    print("[Check-in] Aguardando ~100 segundos para a WebView do Rewards carregar por completo...")
    # Damos 10s para o carregamento inicial da webview
    time.sleep(10)

    # Identificar a posição limite baseada no título "Sequência" para ignorar o "Indique e Ganhe"
    def find_sequence_title_y():
        xml = get_ui_dump(retries=2)
        if not xml:
            return None
        try:
            root = ET.fromstring(xml)
            for node in root.iter('node'):
                t = (node.get('text') or '').lower()
                c = (node.get('content-desc') or '').lower()
                # Procuramos termos em português ou inglês para a área da sequência
                if 'sequên' in t or 'sequen' in t or 'streak' in t or 'sequên' in c or 'sequen' in c or 'streak' in c:
                    b = parse_bounds(node.get('bounds', ''))
                    # Retorna a coordenada Y inferior do título para limite
                    print(f"[Check-in] Título 'Sequência' detectado em {b}. Limitando busca das moedas a Y > {b[3]}.")
                    return b[3]
        except Exception as e:
            print(f"[Check-in] Erro ao buscar título 'Sequência' no XML: {e}")
        return None

    seq_y = find_sequence_title_y()
    if seq_y is None:
        seq_y = 1780  # Fallback seguro caso o XML não carregue/mostre o texto
        print(f"[Check-in] Título 'Sequência' não localizado no XML. Usando Y > {seq_y} como fallback de segurança.")

    # Tirar SS para achar palavra Check-in
    def take_screenshot_img(filename):
        run_adb(f"shell screencap -p /sdcard/{filename}")
        run_adb(f"pull /sdcard/{filename} {filename}", timeout_sec=10)
        if os.path.exists(filename):
            try:
                return Image.open(filename).convert("RGB")
            except: pass
        return None

    def find_checkin_text(img, min_y):
        """Ao inves de procurar texto branco (que confunde com outros banners),
        procura a faixa horizontal de moedas douradas, e retorna a coordenada
        exata da palavra 'Check-in' que fica imediatamente acima delas.
        """
        if img is None: return None
        gold_y = []
        # Limita a busca vertical a partir de min_y para ignorar o "Indique e Ganhe"
        start_y = max(800, min_y)
        for y in range(start_y, 2100, 10):
            for x in range(100, 700, 10):
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
    checkin_pos = find_checkin_text(img_before, seq_y)

    if not checkin_pos:
        print("[Check-in] Nenhuma moeda dourada detectada após o título da sequência. Assumindo check-in coletado.")
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
    checkin_pos_after = find_checkin_text(img_after, seq_y)

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
    # launch_bing() ja faz force-stop internamente antes de reabrir
    launch_bing()

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

    print("[*] Aguardando estabilidade do Bing (10s)...")
    time.sleep(10)
    clear_blocking_modals()
    time.sleep(2)
    
    # Verifica se estamos na Home do Bing (e nao na pesquisa ou outra tela)
    xml = get_ui_dump(retries=2)
    if xml:
        # Se detectar a barra de pesquisa ativa/focada, pressiona Back para voltar à Home
        if 'SearchTextInput' in xml or ('search' in xml.lower() and 'focusable="true" focused="true"' in xml):
            print("[AVISO] Tela de pesquisa detectada em vez da Home. Pressionando Back...")
            back()
            time.sleep(3)

    # Tentativa de Check-in (até 3 vezes)
    checkin_ok = False
    for att in range(3):
        print(f"[Check-in] Tentativa {att+1}/3...")
        try:
            if do_daily_checkin():
                checkin_ok = True
                stats["checkin_report"] = "✅ Concluido"
                break
        except Exception as e:
            print(f"[Erro] Falha no Check-in: {e}")
        time.sleep(3)
        
    if not checkin_ok:
        stats["checkin_report"] = "❌ Falhou"

    # Tentativa de Leitura de Notícias (até 3 vezes)
    news_ok = False
    pts_originais = None
    for att in range(3):
        print(f"\n[Notícias] Tentativa {att+1}/3 de leitura de notícias...")
        try:
            rewards_bounds = ensure_bing_home_and_rewards_visible(max_retries=3)
            if not rewards_bounds:
                print("[Notícias] ABORTADO: Widget Rewards não detectado na Home.")
                continue
            
            pts_iniciais, max_pts = get_home_points(do_scroll=True)
            if pts_iniciais is None:
                pts_iniciais, max_pts = 0, 210
            print(f"[*] Pontos antes das notícias: {pts_iniciais}/{max_pts}")
            
            if pts_originais is None:
                pts_originais = pts_iniciais
            
            if pts_iniciais >= max_pts and max_pts > 0:
                stats["news_report"] = "✅ Já concluído"
                stats["pts_final"] = pts_iniciais
                stats["pts_max"] = max_pts
                news_ok = True
                break
                
            pts_finais, _ = read_news_logic(pts_iniciais, max_pts, news_override=None)
            total_ganhos = pts_finais - pts_originais
            print(f"[*] Notícias concluídas na tentativa {att+1}. Total acumulado de pontos ganhos: {total_ganhos}")
            
            if total_ganhos >= 30 or (pts_finais >= max_pts and max_pts > 0):
                stats["news_report"] = f"✅ Concluido (+{total_ganhos} pts)"
                news_ok = True
                stats["pts_final"] = pts_finais
                stats["pts_max"] = max_pts
                break
            else:
                stats["news_report"] = f"❌ Incompleto (+{total_ganhos} pts, {pts_finais}/{max_pts})"
                stats["pts_final"] = pts_finais
                stats["pts_max"] = max_pts
        except Exception as e:
            print(f"[Erro] Falha nas Notícias: {e}")
        time.sleep(3)

    run_adb("shell am force-stop com.microsoft.bing")
    return stats

async def run_full_automation():
    os.system("taskkill /F /IM msedge.exe /T 2>NUL")
    
    relatorio = {
        "hora": datetime.now().strftime("%H:%M"),
        "reivindicar": "❌ Não verificado",
        "diario": "❌ Não verificado",
        "pesquisas": "❌ Não verificado",
        "extras": "❌ Não verificado",
        "checkin": "❌ Não verificado",
        "news": "❌ Não verificado",
        "pts_final": 0,
        "pts_max": 210
    }

    async with async_playwright() as p:
        try:
            print("[Web] Iniciando navegador Edge...")
            context = await p.chromium.launch_persistent_context(
                user_data_dir=os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data"),
                channel="msedge", headless=False, no_viewport=True, args=["--start-maximized"]
            )
            
            # Etapa 1: Reivindicar Pontos
            print("\n=== ETAPA 1: REIVINDICAR PONTOS ===")
            page = context.pages[0] if context.pages else await context.new_page()
            
            claim_status = "Falhou"
            for att in range(3):
                try:
                    await page.goto("https://rewards.bing.com/dashboard", wait_until="domcontentloaded", timeout=15000)
                    await human_delay(3000, 5000)
                    try:
                        await page.screenshot(path="dashboard_screenshot.png")
                        html = await page.content()
                        with open("dashboard_dump.html", "w", encoding="utf-8") as f:
                            f.write(html)
                        print("[Debug] Screenshot salvo em dashboard_screenshot.png e HTML em dashboard_dump.html")
                    except Exception as debug_err:
                        print(f"[Debug] Erro ao salvar artefatos de depuração: {debug_err}")
                    claim_status, _ = await claim_points_if_available(page)
                    if "falha" not in claim_status.lower():
                        break
                except Exception as e:
                    print(f"[Erro] Falha ao tentar reivindicar pontos (tentativa {att+1}/3): {e}")
            relatorio["reivindicar"] = claim_status
            
            # Etapa 2: Conjunto Diário
            diario_status, _ = await run_daily_sets_workflow(context, len(context.pages))
            relatorio["diario"] = diario_status
            
            # Etapa 3: Pesquisas Web (60 pontos)
            pesquisas_status, _ = await check_and_perform_searches(context)
            relatorio["pesquisas"] = pesquisas_status
            
            # Etapa 4: Continuar Ganhando
            extras_status, _ = await do_keep_earning(context, len(context.pages))
            relatorio["extras"] = extras_status
            
            # Fecha contexto do navegador
            await context.close()
            
        except Exception as e:
            print(f"[Erro] Falha na execução Web: {e}")
            
    # Etapa 5: Celular (ADB Mobile)
    print("\n=== ETAPA 5: CELULAR (ADB MOBILE) ===")
    try:
        app = run_bing_app_automation()
        relatorio["checkin"] = app.get("checkin_report", "❌ Falhou")
        relatorio["news"] = app.get("news_report", "❌ Falhou")
        relatorio["pts_final"] = app.get("pts_final", 0)
        relatorio["pts_max"] = app.get("pts_max", 210)
    except Exception as e:
        print(f"[Erro] Falha na execução Mobile: {e}")
        
    kill_emulator()
    return relatorio

async def main():
    print(f"\n=== INICIANDO EXECUÇÃO UNICA COM RETENTATIVAS LOCAIS ===")
    relatorio = await run_full_automation()

    msg = (f"RELATORIO BING AUTO - {relatorio['hora']}\n\n"
           f"Reivindicar: {relatorio['reivindicar']}\n"
           f"Daily Set: {relatorio['diario']}\n"
           f"Pesquisas (60 pts): {relatorio['pesquisas']}\n"
           f"Pontos Extras: {relatorio['extras']}\n"
           f"Check-in Celular: {relatorio['checkin']}\n"
           f"Noticias Celular: {relatorio['news']}\n"
           f"Pontuacao Final Celular: {relatorio['pts_final']}/{relatorio['pts_max']}\n")

    # Message telegram with emojis
    msg_telegram = (f"\U0001f680 *RELATORIO BING AUTO - {relatorio['hora']}*\n\n"
                    f"\U0001f4c5 *Reivindicar:* {relatorio['reivindicar']}\n"
                    f"\U0001f4bb *Daily Set:* {relatorio['diario']}\n"
                    f"\U0001f4c4 *Pesquisas (60 pts):* {relatorio['pesquisas']}\n"
                    f"\U0001fa99 *Pontos Extras:* {relatorio['extras']}\n"
                    f"\U0001f4f1 *Check-in Celular:* {relatorio['checkin']}\n"
                    f"\U0001f4f0 *Noticias Celular:* {relatorio['news']}\n\n"
                    f"\U0001f3c6 *Pontuacao Final Celular:* {relatorio['pts_final']}/{relatorio['pts_max']}")

    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))
    
    send_telegram_msg(msg_telegram)
    os.system("taskkill /F /IM msedge.exe /T 2>NUL")
    kill_emulator()

if __name__ == "__main__":
    asyncio.run(main())