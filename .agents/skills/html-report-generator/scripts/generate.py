import json
import os
import webbrowser
import http.server
import socketserver
import threading
import time

def generate_html(apartments):
    html = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Результаты поиска квартир</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; margin: 0; padding: 20px; }
            h1 { text-align: center; color: #2c3e50; }
            .container { display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; max-width: 1200px; margin: 0 auto; }
            .card { background: #fff; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); overflow: hidden; width: 320px; transition: transform 0.2s; }
            .card:hover { transform: translateY(-5px); }
            .card img { width: 100%; height: 200px; object-fit: cover; }
            .card-content { padding: 15px; }
            .card-title { font-size: 1.2em; font-weight: bold; margin-bottom: 10px; color: #2980b9; }
            .card-price { font-size: 1.4em; color: #e74c3c; font-weight: bold; margin-bottom: 10px; }
            .card-desc { font-size: 0.9em; color: #7f8c8d; margin-bottom: 15px; line-height: 1.4; height: 60px; overflow: hidden; text-overflow: ellipsis; }
            .card-btn { display: block; text-align: center; background: #3498db; color: #fff; text-decoration: none; padding: 10px; border-radius: 5px; font-weight: bold; }
            .card-btn:hover { background: #2980b9; }
        </style>
    </head>
    <body>
        <h1>Найденные квартиры</h1>
        <div class="container">
    """

    for apt in apartments:
        title = apt.get("title", "Квартира")
        price = apt.get("price", "Цена не указана")
        desc = apt.get("description", "")[:100] + "..."
        url = apt.get("url", "#")
        
        photos = apt.get("photos", [])
        photo_url = photos[0] if photos else "https://via.placeholder.com/320x200?text=No+Photo"

        html += f"""
            <div class="card">
                <img src="{photo_url}" alt="Фото">
                <div class="card-content">
                    <div class="card-price">{price} ₸</div>
                    <div class="card-title">{title}</div>
                    <div class="card-desc">{desc}</div>
                    <a href="{url}" class="card-btn" target="_blank">Смотреть объявление</a>
                </div>
            </div>
        """

    html += """
        </div>
    </body>
    </html>
    """
    
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html)

def serve():
    PORT = 8080
    Handler = http.server.SimpleHTTPRequestHandler
    
    # Run server in a daemon thread so it doesn't block forever
    # but for a quick tool, we might just block or run briefly
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Сервер запущен на http://localhost:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    try:
        with open("apartments.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print("Файл apartments.json не найден. Используются тестовые данные.")
        data = [{
            "title": "2-комнатная квартира, 54 м²",
            "price": "350000",
            "description": "Отличная квартира в центре города. Рядом Мегапарк, метро, развитая инфраструктура.",
            "url": "https://krisha.kz/",
            "photos": ["https://via.placeholder.com/320x200?text=Test+Photo"]
        }]

    generate_html(data)
    
    # Open browser
    webbrowser.open("http://localhost:8080/report.html")
    
    # Start server
    try:
        serve()
    except KeyboardInterrupt:
        print("Сервер остановлен.")
