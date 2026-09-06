# livoix

Transforme un PDF en livre audio MP3, avec une voix naturelle et la bonne
langue détectée automatiquement.

Le MP3 est créé **à côté du PDF**, sous le même nom.

## Installation

Il faut Python 3.8 ou plus récent : https://www.python.org/downloads/
(coche **"Add Python to PATH"** pendant l'installation).

Ensuite, rien à faire : **`livoix.bat` installe les dépendances tout seul au
premier lancement.**

Pour les installer à la main :

```
pip install -r requirements.txt
```

## Utilisation

**Le plus simple** — double-clique sur `livoix.bat`, puis colle le chemin de
ton PDF et appuie sur Entrée. Tu peux glisser-déposer le PDF dans la fenêtre :
les guillemets sont gérés.

**En ligne de commande :**

```
python livoix.py "C:\chemin\vers\mon_livre.pdf"
```

## Langues

La langue du livre est détectée automatiquement et la voix est choisie en
conséquence : français, anglais, espagnol, allemand, italien, portugais,
néerlandais, polonais, russe, japonais, chinois, arabe. Si la langue n'est pas
reconnue, c'est le français qui est utilisé.

## Bon à savoir

- **Une connexion internet est obligatoire** : la synthèse vocale passe par les
  serveurs de Microsoft (`edge-tts`). Le service est gratuit, sans clé d'API.
- **Les PDF scannés ne marchent pas.** Si le PDF est une suite d'images, il n'y
  a pas de texte à extraire — il faut d'abord passer un OCR (Adobe Acrobat,
  Tesseract). Le script te le dit clairement au lieu de planter.
- Compte environ **1 minute d'audio pour 150 mots**. Le script t'annonce la
  durée estimée avant de lancer la génération.
- Si le MP3 existe déjà, il te demande avant d'écraser.

## Fichiers

| Fichier | Rôle |
|---|---|
| `livoix.py` | Le script : extraction, nettoyage du texte, synthèse vocale |
| `livoix.bat` | Lanceur Windows (installe les dépendances, demande le chemin) |
| `requirements.txt` | Les 3 dépendances |
