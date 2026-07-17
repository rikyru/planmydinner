import { defineComponent } from 'vue';
import { prepareImage } from './mensa.js?v=3';

const Recipes = defineComponent({
    name: 'Recipes',
    inject: ['toast'],
    template: `
        <div class="recipes-view">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
                <h2>Ricette</h2>
                <div style="display:flex;gap:8px;flex-wrap:wrap;">
                    <button @click="deleteAllRecipes" class="btn-danger" :disabled="recipes.length === 0">🗑️ Elimina tutte</button>
                    <label class="btn-secondary" style="cursor:pointer;">
                        {{ photoAnalyzing ? '🔎 Analisi...' : '📷 Da foto' }}
                        <input type="file" accept="image/*" style="display:none"
                               :disabled="photoAnalyzing" @change="recipeFromPhoto">
                    </label>
                    <button @click="openAdd" class="btn-primary">+ Aggiungi ricetta</button>
                </div>
            </div>

            <div v-if="loading" class="loading">Caricamento...</div>

            <!-- Importa in blocco -->
            <div class="card" style="margin-bottom:20px;">
                <div style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;"
                     @click="showBulk = !showBulk">
                    <h3 style="margin:0;">📥 Importa in blocco (JSON)</h3>
                    <span style="font-size:18px;color:#868e96;">{{ showBulk ? '▲' : '▼' }}</span>
                </div>

                <div v-if="showBulk" style="margin-top:16px;">
                    <p style="font-size:13px;color:#495057;margin:0 0 8px;">
                        Incolla un array JSON di ricette nel formato semplificato.
                        Puoi farlo generare a ChatGPT con questo prompt:<br>
                        <em>"Genera 10 ricette in formato JSON array con i campi: name (string), time (minuti, int), difficulty (facile/media/difficile), mood (normale/veloce/festivo/leggero), cooking (tegame/forno/vapore/griglia/crudo), ingredients (array di {name, food_group (carboidrati/proteina/verdure/legumi/latticini/condimenti), grams}). Formato esatto: [{...}, {...}]"</em>
                    </p>

                    <details style="margin-bottom:10px;">
                        <summary style="cursor:pointer;font-size:13px;color:#4263eb;">Mostra formato esempio</summary>
                        <pre style="background:#f1f3f5;border-radius:6px;padding:10px;font-size:12px;overflow-x:auto;margin-top:6px;">{{ exampleJson }}</pre>
                    </details>

                    <textarea v-model="bulkJson"
                              rows="8"
                              placeholder='[{"name":"Pollo al limone","time":25,"difficulty":"facile","mood":"normale","cooking":"tegame","ingredients":[{"name":"Petto di pollo","food_group":"proteina","grams":150}]}]'
                              style="width:100%;font-family:monospace;font-size:12px;padding:8px;border:1px solid #ced4da;border-radius:6px;resize:vertical;">
                    </textarea>

                    <div style="display:flex;align-items:center;gap:12px;margin-top:10px;">
                        <button @click="runBulkImport" class="btn-primary" :disabled="bulkLoading || !bulkJson.trim()">
                            {{ bulkLoading ? 'Importazione...' : '📥 Importa' }}
                        </button>
                        <span v-if="bulkResult" :style="{color: bulkResult.errors.length ? '#e67700' : '#2f9e44', fontSize:'13px'}">
                            ✅ {{ bulkResult.created }} importate
                            <span v-if="bulkResult.skipped"> · ⏭ {{ bulkResult.skipped }} saltate (già esistenti)</span>
                            <span v-if="bulkResult.errors.length"> · ⚠️ {{ bulkResult.errors.length }} errori</span>
                        </span>
                        <span v-if="bulkError" style="color:#c92a2a;font-size:13px;">{{ bulkError }}</span>
                    </div>
                    <ul v-if="bulkResult && bulkResult.errors.length" style="color:#c92a2a;font-size:12px;margin-top:6px;">
                        <li v-for="e in bulkResult.errors" :key="e">{{ e }}</li>
                    </ul>
                </div>
            </div>

            <!-- Catalogo pasti mensa (da foto) -->
            <div class="card" style="margin-bottom:20px;">
                <div style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;"
                     @click="showMensa = !showMensa">
                    <h3 style="margin:0;">🍱 Pasti da foto <span class="hint" v-if="mensaMeals.length">({{ mensaMeals.length }})</span></h3>
                    <span style="font-size:18px;color:var(--text-3);">{{ showMensa ? '▲' : '▼' }}</span>
                </div>

                <div v-if="showMensa" style="margin-top:14px;">
                    <p class="hint" style="margin:0 0 10px;">
                        I pasti mappati dalla foto (mensa, ristorante, casa...). Correggi qui nomi e grammature:
                        le modifiche valgono anche per i macro dei consumi già registrati.
                    </p>
                    <div v-if="mensaMeals.length === 0" class="hint">Nessun pasto ancora: usa "📷 Da foto" dalla vista Oggi o dal popup del giorno.</div>

                    <div v-for="m in mensaMeals" :key="m.id"
                         style="border:1px solid var(--border);border-radius:10px;padding:10px 12px;margin-bottom:8px;">
                        <!-- Riga compatta -->
                        <div style="display:flex;align-items:center;gap:10px;cursor:pointer;" @click="toggleMensaEdit(m)">
                            <strong style="flex:1;">{{ m.name }}</strong>
                            <span class="hint" v-if="m.nutrition">~{{ Math.round(m.nutrition.kcal) }} kcal</span>
                            <span class="hint">usato {{ m.usage_count }}×</span>
                            <span style="color:var(--text-3);">{{ mensaEditId === m.id ? '▲' : '✏️' }}</span>
                        </div>

                        <!-- Editor espanso -->
                        <div v-if="mensaEditId === m.id" style="margin-top:10px;display:flex;flex-direction:column;gap:8px;">
                            <input v-model="mensaEdit.name" placeholder="Nome pasto">
                            <div v-for="(ing, idx) in mensaEdit.ingredients" :key="idx"
                                 style="display:grid;grid-template-columns:1fr 90px auto;gap:8px;align-items:center;">
                                <input v-model="ing.name">
                                <input v-model.number="ing.grams" type="number" min="0" step="10">
                                <button @click="mensaEdit.ingredients.splice(idx, 1)" class="btn-secondary btn-sm">✕</button>
                            </div>
                            <div style="display:flex;gap:8px;margin-top:4px;">
                                <button @click="saveMensaEdit" class="btn-primary btn-sm"
                                        :disabled="mensaSaving || !mensaEdit.name || !mensaEdit.ingredients.length">
                                    {{ mensaSaving ? 'Salvataggio...' : '💾 Salva' }}
                                </button>
                                <button @click="mensaEditId = null" class="btn-secondary btn-sm">Annulla</button>
                                <button @click="deleteMensa(m)" class="btn-danger btn-sm" style="margin-left:auto;">🗑️ Elimina</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div v-if="!loading && recipes.length === 0" class="empty-state">
                <p>Nessuna ricetta nel catalogo. Aggiungine una!</p>
            </div>

            <table v-if="!loading && recipes.length > 0" class="recipe-table">
                <thead>
                    <tr>
                        <th>Nome</th>
                        <th>Ingrediente principale</th>
                        <th>Tempo</th>
                        <th>Difficoltà</th>
                        <th>Azioni</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="r in recipes" :key="r.id">
                        <td>
                            <span class="recipe-name-cell">{{ r.name }}</span>
                            <span v-if="r.tags && r.tags.manual" class="badge-manual">⭐ Personale</span>
                            <span v-if="r.tags && r.tags.imported" class="badge-imported">📥 Importata</span>
                        </td>
                        <td>{{ mainIngredientLabel(r) }}</td>
                        <td>{{ r.total_time_minutes ? r.total_time_minutes + ' min' : '—' }}</td>
                        <td>{{ r.difficulty || '—' }}</td>
                        <td>
                            <button @click="openEdit(r)" class="btn-sm">Modifica</button>
                            <button @click="deleteRecipe(r.id)" class="btn-sm btn-danger">Elimina</button>
                        </td>
                    </tr>
                </tbody>
            </table>

            <!-- Modal aggiungi/modifica -->
            <div v-if="showModal" class="modal-overlay" @click.self="closeModal">
                <div class="modal" style="max-width:560px;max-height:90vh;overflow-y:auto;">
                    <h3>{{ editedRecipe.id ? 'Modifica ricetta' : 'Nuova ricetta' }}</h3>

                    <div class="form-section">
                        <label>Nome ricetta *</label>
                        <input v-model="editedRecipe.name" placeholder="Es. Pollo al limone con patate">
                    </div>

                    <div class="form-row" style="gap:12px;">
                        <div class="form-section" style="flex:1">
                            <label>Tempo (minuti)</label>
                            <input v-model.number="editedRecipe.total_time_minutes" type="number" min="5" step="5">
                        </div>
                        <div class="form-section" style="flex:1">
                            <label>Difficoltà</label>
                            <select v-model="editedRecipe.difficulty">
                                <option value="facile">Facile</option>
                                <option value="media">Media</option>
                                <option value="difficile">Difficile</option>
                            </select>
                        </div>
                    </div>

                    <div class="form-row" style="gap:12px;">
                        <div class="form-section" style="flex:1">
                            <label>Umore</label>
                            <select v-model="editedRecipe.mood">
                                <option value="normale">Normale</option>
                                <option value="veloce">Veloce</option>
                                <option value="festivo">Festivo</option>
                                <option value="leggero">Leggero</option>
                            </select>
                        </div>
                        <div class="form-section" style="flex:1">
                            <label>Cottura</label>
                            <select v-model="editedRecipe.cooking_method">
                                <option value="tegame">Tegame</option>
                                <option value="forno">Forno</option>
                                <option value="vapore">Vapore</option>
                                <option value="griglia">Griglia</option>
                                <option value="crudo">Crudo</option>
                                <option value="bollitura">Bollitura</option>
                            </select>
                        </div>
                    </div>

                    <div class="form-section">
                        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
                            <label style="margin:0">Ingredienti</label>
                            <button @click="addIngredient" class="btn-sm">+ Aggiungi</button>
                        </div>
                        <table class="ingredient-table">
                            <thead>
                                <tr>
                                    <th>Nome</th>
                                    <th>Gruppo alimentare</th>
                                    <th>Grammi</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="(ing, idx) in editedRecipe.ingredients" :key="idx">
                                    <td><input v-model="ing.name" placeholder="Es. Pollo" style="width:100%"></td>
                                    <td>
                                        <select v-model="ing.food_group" style="width:100%">
                                            <option value="carboidrati">Carboidrati</option>
                                            <option value="proteina">Proteina (generica)</option>
                                            <option value="carne_bianca">Carne bianca</option>
                                            <option value="carne_rossa">Carne rossa</option>
                                            <option value="pesce">Pesce</option>
                                            <option value="uova">Uova</option>
                                            <option value="legumi">Legumi</option>
                                            <option value="latticini">Latticini</option>
                                            <option value="verdure">Verdure</option>
                                            <option value="grassi">Grassi</option>
                                            <option value="condimenti">Condimenti</option>
                                            <option value="altro">Altro</option>
                                        </select>
                                    </td>
                                    <td><input v-model.number="ing.grams" type="number" min="0" step="5" style="width:70px"> g</td>
                                    <td><button @click="removeIngredient(idx)" class="btn-sm btn-danger">×</button></td>
                                </tr>
                            </tbody>
                        </table>
                        <div v-if="editedRecipe.ingredients.length === 0" style="color:#999;font-size:13px;margin-top:6px;">
                            Aggiungi almeno un ingrediente.
                        </div>
                    </div>

                    <div style="display:flex;gap:10px;margin-top:20px;">
                        <button @click="saveRecipe"
                                class="btn-primary"
                                :disabled="!editedRecipe.name || editedRecipe.ingredients.length === 0">
                            Salva
                        </button>
                        <button @click="closeModal" class="btn-secondary">Annulla</button>
                    </div>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            recipes: [],
            loading: false,
            showModal: false,
            editedRecipe: this._emptyRecipe(),
            // Catalogo pasti mensa
            showMensa: false,
            mensaMeals: [],
            mensaEditId: null,
            mensaEdit: { name: '', ingredients: [] },
            mensaSaving: false,
            photoAnalyzing: false,
            profiles: [],
            // Bulk import
            showBulk: false,
            bulkJson: '',
            bulkLoading: false,
            bulkResult: null,
            bulkError: null,
            exampleJson: JSON.stringify([
                {
                    name: "Pollo al limone",
                    time: 25,
                    difficulty: "facile",
                    mood: "normale",
                    cooking: "tegame",
                    ingredients: [
                        { name: "Petto di pollo", food_group: "proteina", grams: 150 },
                        { name: "Patate", food_group: "verdure", grams: 120 },
                    ],
                },
                {
                    name: "Pasta alla norma",
                    time: 30,
                    difficulty: "facile",
                    mood: "normale",
                    cooking: "tegame",
                    ingredients: [
                        { name: "Pasta", food_group: "carboidrati", grams: 80 },
                        { name: "Melanzane", food_group: "verdure", grams: 150 },
                    ],
                },
            ], null, 2),
        };
    },
    methods: {
        // --- Ricetta da foto ---
        async fetchProfiles() {
            try {
                const resp = await window.apiFetch('/profiles/');
                this.profiles = resp.ok ? await resp.json() : [];
            } catch (_) { this.profiles = []; }
        },
        async recipeFromPhoto(ev) {
            const file = ev.target.files?.[0];
            if (!file) return;
            this.photoAnalyzing = true;
            try {
                const prepared = await prepareImage(file);
                const form = new FormData();
                form.append('file', prepared, prepared.name || 'ricetta.jpg');
                const pid = this.profiles[0]?.id || 'persona_a';
                const resp = await window.apiFetch('/consumed-entries/photo/analyze?profile_id=' + encodeURIComponent(pid), {
                    method: 'POST', body: form,
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'Analisi fallita.');
                }
                const proposal = await resp.json();
                // Pre-compila il modal di modifica: l'utente aggiusta e salva nel catalogo
                this.editedRecipe = {
                    id: null,
                    name: proposal.name,
                    total_time_minutes: 30,
                    difficulty: 'facile',
                    mood: 'normale',
                    cooking_method: 'tegame',
                    ingredients: proposal.ingredients.map(i => ({
                        name: i.name, food_group: i.food_group || 'altro', grams: i.grams,
                    })),
                };
                this.showModal = true;
                this.toast.add('Ricetta riconosciuta: controlla e salva!', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.photoAnalyzing = false;
                ev.target.value = '';
            }
        },

        // --- Catalogo pasti mensa ---
        async fetchMensaMeals() {
            try {
                const resp = await window.apiFetch('/consumed-entries/mensa');
                this.mensaMeals = resp.ok ? await resp.json() : [];
            } catch (_) {
                this.mensaMeals = [];
            }
        },
        toggleMensaEdit(m) {
            if (this.mensaEditId === m.id) { this.mensaEditId = null; return; }
            this.mensaEditId = m.id;
            this.mensaEdit = {
                name: m.name,
                ingredients: m.ingredients.map(i => ({ name: i.name, food_group: i.food_group || 'altro', grams: i.grams })),
            };
        },
        async saveMensaEdit() {
            this.mensaSaving = true;
            try {
                const body = {
                    name: this.mensaEdit.name,
                    ingredients: this.mensaEdit.ingredients.filter(i => i.name && i.grams > 0),
                };
                const resp = await window.apiFetch(`/consumed-entries/mensa/${this.mensaEditId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.toast.add('Pasto mensa aggiornato!', 'success');
                this.mensaEditId = null;
                await this.fetchMensaMeals();
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.mensaSaving = false;
            }
        },
        async deleteMensa(m) {
            if (!confirm(`Eliminare "${m.name}" dal catalogo mensa?`)) return;
            try {
                const resp = await window.apiFetch(`/consumed-entries/mensa/${m.id}`, { method: 'DELETE' });
                if (!resp.ok) throw new Error(await resp.text());
                this.toast.add('Pasto mensa eliminato.', 'success');
                this.mensaEditId = null;
                await this.fetchMensaMeals();
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },

        _emptyRecipe() {
            return {
                id: null,
                name: '',
                total_time_minutes: 30,
                difficulty: 'facile',
                mood: 'normale',
                cooking_method: 'tegame',
                ingredients: [
                    { name: '', food_group: 'proteina', grams: 150 },
                ],
            };
        },
        async fetchRecipes() {
            this.loading = true;
            try {
                const resp = await window.apiFetch('/recipes/');
                this.recipes = await resp.json();
            } catch (e) {
                this.toast.add('Errore nel caricamento ricette: ' + e.message, 'error');
            } finally {
                this.loading = false;
            }
        },
        openAdd() {
            this.editedRecipe = this._emptyRecipe();
            this.showModal = true;
        },
        openEdit(recipe) {
            // Ricostruisce la struttura piatta dal formato backend
            const ingredients = (recipe.content || []).map(ing => {
                const quantities = ing.quantities || {};
                const firstKey = Object.keys(quantities)[0];
                const grams = firstKey ? (quantities[firstKey].grams_equiv ?? quantities[firstKey].qty ?? 0) : 0;
                return { name: ing.name, food_group: ing.food_group, grams: Math.round(grams) };
            });
            this.editedRecipe = {
                id: recipe.id,
                name: recipe.name,
                total_time_minutes: recipe.total_time_minutes || 30,
                difficulty: recipe.difficulty || 'facile',
                mood: recipe.tags?.mood?.[0] || 'normale',
                cooking_method: recipe.tags?.cooking_methods?.[0] || 'tegame',
                ingredients: ingredients.length > 0 ? ingredients : [{ name: '', food_group: 'proteina', grams: 150 }],
            };
            this.showModal = true;
        },
        closeModal() {
            this.showModal = false;
        },
        addIngredient() {
            this.editedRecipe.ingredients.push({ name: '', food_group: 'verdure', grams: 100 });
        },
        removeIngredient(idx) {
            this.editedRecipe.ingredients.splice(idx, 1);
        },
        _buildPayload() {
            const pA = localStorage.getItem('profile_a_id') || 'persona_a';
            const pB = localStorage.getItem('profile_b_id') || 'persona_b';
            const content = this.editedRecipe.ingredients.map(ing => ({
                name: ing.name,
                food_group: ing.food_group,
                quantities: {
                    [pA]: { qty: ing.grams, unit: 'g', grams_equiv: ing.grams },
                    [pB]: { qty: ing.grams, unit: 'g', grams_equiv: ing.grams },
                },
            }));
            return {
                name: this.editedRecipe.name,
                total_time_minutes: this.editedRecipe.total_time_minutes,
                difficulty: this.editedRecipe.difficulty,
                content,
                steps: [],
                tags: {
                    mood: [this.editedRecipe.mood],
                    cooking_methods: [this.editedRecipe.cooking_method],
                    cleanup: ['facile'],
                },
            };
        },
        async saveRecipe() {
            if (!this.editedRecipe.name || this.editedRecipe.ingredients.length === 0) return;
            const isEdit = !!this.editedRecipe.id;
            const url = isEdit ? `/recipes/${this.editedRecipe.id}` : '/recipes/';
            const method = isEdit ? 'PUT' : 'POST';
            try {
                const resp = await window.apiFetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this._buildPayload()),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeModal();
                await this.fetchRecipes();
                this.toast.add(isEdit ? 'Ricetta aggiornata!' : 'Ricetta aggiunta!', 'success');
            } catch (e) {
                this.toast.add('Errore nel salvataggio: ' + e.message, 'error');
            }
        },
        async deleteAllRecipes() {
            if (!confirm(`Eliminare tutte le ${this.recipes.length} ricette? Questa azione è irreversibile.`)) return;
            try {
                const resp = await window.apiFetch('/recipes/all', { method: 'DELETE' });
                if (!resp.ok) throw new Error(await resp.text());
                const result = await resp.json();
                await this.fetchRecipes();
                this.toast.add(`🗑️ ${result.deleted} ricette eliminate.`, 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },
        async deleteRecipe(id) {
            if (!confirm('Eliminare questa ricetta?')) return;
            try {
                const resp = await window.apiFetch(`/recipes/${id}`, { method: 'DELETE' });
                if (!resp.ok) throw new Error(await resp.text());
                await this.fetchRecipes();
                this.toast.add('Ricetta eliminata.', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },
        async runBulkImport() {
            this.bulkResult = null;
            this.bulkError = null;
            let items;
            try {
                items = JSON.parse(this.bulkJson);
                if (!Array.isArray(items)) throw new Error('Il JSON deve essere un array [...]');
            } catch (e) {
                this.bulkError = 'JSON non valido: ' + e.message;
                return;
            }
            this.bulkLoading = true;
            try {
                const pA = localStorage.getItem('profile_a_id') || 'persona_a';
                const pB = localStorage.getItem('profile_b_id') || 'persona_b';
                const params = new URLSearchParams({ profile_a_id: pA, profile_b_id: pB });
                const resp = await window.apiFetch('/recipes/bulk?' + params, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(items),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.bulkResult = await resp.json();
                if (this.bulkResult.created > 0) {
                    this.toast.add(`${this.bulkResult.created} ricette importate!`, 'success');
                    await this.fetchRecipes();
                }
            } catch (e) {
                this.bulkError = 'Errore: ' + e.message;
            } finally {
                this.bulkLoading = false;
            }
        },
        mainIngredientLabel(recipe) {
            if (!recipe.content || recipe.content.length === 0) return '—';
            const ing = recipe.content[0];
            const quantities = ing.quantities || {};
            const firstKey = Object.keys(quantities)[0];
            const grams = firstKey ? Math.round(quantities[firstKey].grams_equiv ?? quantities[firstKey].qty ?? 0) : 0;
            return `${ing.name} (${grams}g)`;
        },
    },
    mounted() {
        this.fetchRecipes();
        this.fetchMensaMeals();
        this.fetchProfiles();
    },
});

export default Recipes;
