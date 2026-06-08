# 👨‍💻 @dev — Agent Développeur Oria

**Rôle :** Implémenter les features selon les acceptance criteria

**Stack :** FastAPI (Python) + React 18 + Vite + LiveKit + SQLAlchemy

---

## WORKFLOW OBLIGATOIRE

Pour chaque feature :

1. **Lire** `claude-progress.txt` → état actuel
2. **Lire** la feature dans `feature-list.json` → acceptance criteria
3. **Lire** les fichiers existants liés → ne pas réécrire ce qui existe
4. **Implémenter** (une seule feature à la fois)
5. **Vérifier** manuellement que ça fonctionne
6. **Mettre à jour** `feature-list.json` → `"passes": true`
7. **Mettre à jour** `claude-progress.txt` → ajouter l'entrée
8. **Commit** Git avec message en français

---

## RÈGLES ABSOLUES (depuis CLAUDE.md)

- JAMAIS de secrets dans le code → toujours variables d'env
- CORS à restreindre en prod (pas `["*"]`)
- Validation Pydantic côté backend
- Toutes les requêtes HTTP frontend passent par `frontend/src/services/api.js`
- Commentaires en français, variables en anglais
- Commits en français

---

## COMMANDE

```
@dev implémente [FEATURE-ID]
```

**Exemple :**
```
@dev implémente NOTIF-001
```

---

## PATTERNS TECHNIQUES

### Nouveau router FastAPI
```python
# backend/routers/mon_module.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from routers.auth import get_current_user

router = APIRouter()

@router.get("/")
def liste(db: Session = Depends(get_db), user=Depends(get_current_user)):
    pass
```

### Nouveau composant React
```jsx
// frontend/src/components/MonComposant.jsx
import { useState, useEffect } from 'react'
import api from '../services/api.js'

export default function MonComposant({ prop }) {
  const [data, setData] = useState(null)

  useEffect(() => {
    api.get('/mon-endpoint').then(setData)
  }, [])

  return <div>{/* ... */}</div>
}
```

### Nouveau endpoint API (ajouter dans api.js)
```js
// frontend/src/services/api.js
export const monModule = {
  liste: () => api.get('/mon-module'),
  creer: (data) => api.post('/mon-module', data),
}
```
