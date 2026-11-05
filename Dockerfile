# Tableau de bord Maison (avec Garde-manger), pour un hébergeur ou un Raspberry Pi.
FROM python:3.12-slim
WORKDIR /app
COPY garde-manger/requirements.txt garde-manger/requirements.txt
COPY maison/requirements.txt maison/requirements.txt
RUN pip install --no-cache-dir -r maison/requirements.txt
COPY garde-manger garde-manger
COPY maison maison
ENV MAISON_DONNEES=/donnees PORT=8000 PYTHONUNBUFFERED=1
VOLUME /donnees
EXPOSE 8000
CMD ["python", "maison/serveur.py"]
