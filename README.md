# 🤖 Price Scout Bot — Local

Ranking inteligente de productos más vendidos en 7 plataformas e-commerce,
con scraping real, normalización de datos y dashboard web.

## Plataformas soportadas
- MercadoLibre (Argentina)
- Amazon (USA)
- eBay
- AliExpress
- Temu *
- Shein *
- TiendaNube *

> (*) Temu, Shein y TiendaNube tienen protecciones anti-bot agresivas.
> Si el scraping real falla, el bot usa datos sintéticos realistas como fallback
> para que siempre tengas resultados.

---

## Instalación y ejecución

### Requisitos
- Python 3.9 o superior
- pip

### Pasos

```bash
# 1. Entrar a la carpeta del proyecto
cd price_scout

# 2. (Opcional pero recomendado) Crear entorno virtual
python -m venv venv

# En Windows:
venv\Scripts\activate

# En Mac/Linux:
source venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Correr la app
python app.py
```

### 5. Abrir en el browser
```
http://localhost:5000
```

---

## Uso

1. Escribí el nombre del producto (ej: "parlante bluetooth", "vestido verano")
2. Seleccioná una categoría (opcional)
3. Activá/desactivá las plataformas con los chips
4. Ajustá los filtros: precio máximo, rating, tendencia, envío, stock
5. Hacé clic en **Buscar →**
6. Exportá los resultados con **↓ CSV** o **↓ JSON**

---

## Score inteligente

El score (0–100) se calcula como:

```
score = ventas_normalizadas × 0.40
      + rating_normalizado  × 0.30
      + reseñas_normalizadas × 0.20
      + precio_competitivo  × 0.10
```

---

## Notas sobre el scraping

- Amazon y eBay devuelven mejores resultados porque tienen HTML más estable.
- MercadoLibre funciona bien para búsquedas en español.
- AliExpress a veces sirve datos estructurados en `<script>` JSON que el bot parsea.
- Si una plataforma falla (bot detection, timeout), simplemente no aparece en los resultados.
- Para mejorar la tasa de éxito podés usar proxies o Selenium (ver abajo).

### Mejorar con Selenium (opcional)
```bash
pip install selenium webdriver-manager
```
Luego podés reemplazar `requests.get(...)` en cualquier scraper por:
```python
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

options = webdriver.ChromeOptions()
options.add_argument("--headless")
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
driver.get(url)
html = driver.page_source
driver.quit()
soup = BeautifulSoup(html, "html.parser")
```

---

## Estructura del proyecto

```
price_scout/
├── app.py                  # Servidor Flask principal
├── requirements.txt
├── templates/
│   └── index.html          # Dashboard UI completo
└── scrapers/
    ├── __init__.py
    ├── mercadolibre.py
    ├── amazon.py
    ├── ebay.py
    ├── aliexpress.py
    ├── temu.py
    ├── shein.py
    └── tiendanube.py
```

---

## Búsqueda web (Google / DDG / Bing) — Diagnóstico

La búsqueda web raspa los motores de búsqueda en tiempo real.
Si aparece "Sin resultados" en la sección Producto Específico, seguí estos pasos:

### Paso 1 — Verificar conectividad
```bash
python3 -c "import socket; print(socket.gethostbyname('duckduckgo.com'))"
# Si falla con "Name resolution" → problema de red/DNS en tu entorno
```

### Paso 2 — Test manual del scraper
```bash
cd price_scout
python3 -m scrapers.websearch "JBL Go 3"
# Debería mostrar resultados de DDG / Google / Bing
```

### Paso 3 — Si sigue sin funcionar: SerpAPI (recomendado)

SerpAPI ofrece **100 búsquedas gratis por mes** y es la opción más confiable:

1. Registrarte en https://serpapi.com/ (gratis)
2. Copiar tu API key
3. Configurar la variable de entorno:
   ```bash
   # Linux/Mac
   export SERPAPI_KEY="tu_key_aqui"
   python3 app.py

   # Windows
   set SERPAPI_KEY=tu_key_aqui
   python3 app.py
   ```

Con SerpAPI configurado, la búsqueda web usa su API en lugar de scraping directo,
lo que garantiza resultados en cualquier entorno.

### Por qué puede fallar sin SerpAPI
- **IP bloqueada**: Google/DDG bloquean IPs que hacen muchas requests
- **VPN/proxy**: Algunos proveedores tienen IPs en listas negras de buscadores
- **Rate limiting**: Demasiadas búsquedas en poco tiempo
- **CAPTCHA**: Google puede exigir verificación humana
