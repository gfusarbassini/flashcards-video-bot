import pandas as pd
import sys

# La parola viene passata come primo argomento da GitHub Actions
if len(sys.argv) < 2:
    print("Errore: La parola non è stata passata come argomento.")
    sys.exit(1)

new_word = sys.argv[1]
csv_file = 'test_parole.csv'

try:
    # 1. Carica il CSV esistente
    df = pd.read_csv(csv_file)
except FileNotFoundError:
    # Se il file non esiste, crea un nuovo DataFrame con l'intestazione
    df = pd.DataFrame(columns=['Parola'])
except pd.errors.EmptyDataError:
    # Se il file è vuoto ma esiste
    df = pd.DataFrame(columns=['Parola'])

# 2. Crea un nuovo DataFrame per la riga da aggiungere
# Assicurati che l'indice e i nomi delle colonne corrispondano
new_row = pd.DataFrame([new_word], columns=['Parola'])

# 3. Aggiungi la nuova riga
df = pd.concat([df, new_row], ignore_index=True)

# 4. Salva il file CSV aggiornato
df.to_csv(csv_file, index=False)

print(f"Parola '{new_word}' aggiunta con successo a {csv_file}.")
