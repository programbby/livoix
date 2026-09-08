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

**Le plus simple** — double-clique sur `livoix.bat`, colle le chemin de ton PDF
et appuie sur Entrée. Tu peux glisser-déposer le PDF dans la fenêtre : les
guillemets sont gérés. Le script propose ensuite la liste des voix françaises ;
appuie sur Entrée pour laisser la langue être détectée automatiquement.

**En ligne de commande :**

```
python livoix.py "C:\chemin\vers\mon_livre.pdf"
python livoix.py "mon_livre.pdf" --voix 2 --debit +15%
```

| Option | Effet |
|---|---|
| `--voix N` | Choisit une voix française par son numéro (voir plus bas), ou un identifiant complet comme `en-GB-SoniaNeural` |
| `--debit +15%` | Accélère ou ralentit la lecture, de `-50%` à `+100%` |
| `--menu` | Affiche la liste des voix avant de commencer |

Sans `--voix`, la langue du livre est détectée et la voix choisie toute seule.

## Voix françaises

| N° | Voix | Genre | Pays | Note |
|---|---|---|---|---|
| 1 | Rémy | Homme | France | récente, la plus vivante — **défaut** |
| 2 | Vivienne | Femme | France | récente, la plus vivante |
| 3 | Denise | Femme | France | classique, posée |
| 4 | Éloïse | Femme | France | classique, plus jeune |
| 5 | Henri | Homme | France | classique, plate sur la durée |
| 6 | Antoine | Homme | Québec | classique |
| 7 | Sylvie | Femme | Québec | classique |
| 8 | Thierry | Homme | Québec | classique |
| 9 | Gérard | Homme | Belgique | classique |
| 10 | Ariane | Femme | Suisse | classique |

Les voix « Multilingual » (Rémy, Vivienne) sont d'une génération plus récente :
leur intonation varie d'une phrase à l'autre. La différence est mince sur trois
phrases et très nette sur une heure d'écoute — Henri, par exemple, devient
monotone sur la longueur.

## Autres langues

Détectées automatiquement : français, anglais, espagnol, allemand, italien,
portugais, néerlandais, polonais, russe, japonais, chinois, arabe. Si la langue
n'est pas reconnue, c'est le français qui est utilisé.

## Comment ça marche sur un livre entier

Le service de synthèse refuse les textes très longs. livoix découpe donc le
livre en segments d'environ 3000 signes, coupés sur les paragraphes (et sur les
phrases si un paragraphe dépasse à lui seul la limite), génère un MP3 par
segment, puis les assemble.

Concrètement :

- La progression affiche le segment en cours et le **temps restant estimé**.
- Chaque segment est **réessayé jusqu'à 4 fois** avec une attente croissante.
- **La génération reprend où elle s'était arrêtée.** Si tu fermes la fenêtre, si
  le PC s'éteint ou si ça plante au segment 180 sur 200, relance simplement la
  même commande : les 180 premiers sont conservés et seuls les suivants sont
  générés.
- Les segments sont écrits dans `%TEMP%\livoix\`, **jamais à côté de ton PDF**.
  Ils sont effacés une fois le MP3 final assemblé.
- L'assemblage passe par **ffmpeg** s'il est installé, ce qui donne un fichier
  continu. Sans ffmpeg, les segments sont recollés tels quels et un court blanc
  reste audible à chaque raccord (environ toutes les 3 minutes). Pour
  l'installer : `winget install Gyan.FFmpeg`.

## Ce qui est retiré du texte

Un PDF de livre contient beaucoup de choses qui n'ont rien à faire dans un
audio. Sont détectés et écartés :

- la **page de copyright** (ISBN, mentions légales, adresse de l'éditeur) ;
- le **sommaire** en entier — sans ça, l'audio commence par plusieurs minutes de
  « Chapitre 1, Chapitre 2, Chapitre 3… » ;
- les **en-têtes et pieds de page répétés**, repérés parce qu'ils reviennent sur
  au moins un quart des pages ;
- les numéros de page, les URL, les adresses e-mail ;
- les lignes presque sans lettres : tableaux, index, suites de chiffres ;
- les puces isolées et les suites de points ou de tirets.

## Bon à savoir

- **Une connexion internet est obligatoire** : la synthèse vocale passe par les
  serveurs de Microsoft (`edge-tts`). Le service est gratuit, sans clé d'API.
- **Les PDF scannés ne marchent pas.** Si le PDF est une suite d'images, il n'y
  a pas de texte à extraire — il faut d'abord passer un OCR (Adobe Acrobat,
  Tesseract). Le script te le dit clairement au lieu de planter.
- Compte environ **1 minute d'audio pour 150 mots**. Le script annonce la durée
  estimée avant de lancer la génération.
- Si le MP3 existe déjà, il demande avant d'écraser.
- La sortie est du **24 kHz / 48 kbps mono**. C'est fixe côté service : aucun
  réglage ne l'améliore.
- Sur un livre de plusieurs centaines de pages, comptez une à deux heures.
  Empêchez la mise en veille de la machine pendant ce temps.

## Le piège des retours à la ligne

Dans un PDF, un retour à la ligne au milieu d'une phrase vient de la largeur de
la colonne, pas du texte. Si on le laisse tel quel, edge-tts le prononce comme
une pause d'une demi-seconde, et la lecture s'arrête au hasard en plein milieu
des phrases :

> on appelle compte courant le contrat qui lie la banque à son client dans le
> **[pause]** but de transformer leurs créances…

`recoller_lignes()` recolle ces lignes, et ne garde la coupure que dans trois
cas où la pause est voulue : fin de phrase réelle, ligne courte suivie d'une
majuscule (un titre), ou ligne suivante commençant par une puce.

## Fichiers

| Fichier | Rôle |
|---|---|
| `livoix.py` | Le script : extraction, nettoyage, découpage, synthèse vocale |
| `livoix.bat` | Lanceur Windows (installe les dépendances, demande le chemin) |
| `requirements.txt` | Les 3 dépendances |
