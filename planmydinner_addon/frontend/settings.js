import { defineComponent } from 'vue';

const SettingsView = defineComponent({
    name: 'SettingsView',
    inject: ['toast'],
    template: `
        <div class="settings-view">
            <h2>Impostazioni</h2>

            <!-- ── Sezione 1: Configurazione LLM ── -->
            <div class="settings-section">
                <h3 class="settings-section__title">🤖 Configurazione LLM</h3>
                <div class="settings-section__body">
                    <div class="settings-field">
                        <label>Provider</label>
                        <select v-model="config.llm_provider">
                            <option value="openai">OpenAI (GPT)</option>
                            <option value="ollama">Ollama (locale)</option>
                        </select>
                    </div>

                    <div class="settings-field">
                        <label>Modello</label>
                        <input v-model="config.llm_model" type="text"
                               :placeholder="config.llm_provider === 'openai' ? 'es. gpt-4o-mini' : 'es. llama3'">
                    </div>

                    <div class="settings-field">
                        <label>Modello vision (foto pasti)</label>
                        <input v-model="config.llm_vision_model" type="text"
                               :placeholder="config.llm_provider === 'openai' ? 'es. gpt-4o (vuoto = modello principale)' : 'es. llava (vuoto = modello principale)'">
                        <span class="settings-hint">
                            Usato solo per analizzare le foto dei pasti. Lascia vuoto per usare il modello principale.
                        </span>
                    </div>

                    <div class="settings-field">
                        <label>Chiave API
                            <span v-if="hasApiKey" class="settings-key-badge">✓ Configurata</span>
                        </label>
                        <input v-model="config.llm_api_key" type="password"
                               placeholder="Lascia vuoto per non modificarla"
                               autocomplete="new-password">
                        <span class="settings-hint" v-if="config.llm_provider === 'ollama'">
                            Non necessaria per Ollama locale.
                        </span>
                    </div>

                    <div class="settings-field" v-if="config.llm_provider === 'ollama'">
                        <label>Base URL</label>
                        <input v-model="config.llm_base_url" type="text"
                               placeholder="es. http://localhost:11434">
                    </div>

                    <div class="settings-field">
                        <label>Temperature: <strong>{{ (config.llm_temperature || 0.7).toFixed(1) }}</strong></label>
                        <div class="temperature-row">
                            <input type="range" v-model.number="config.llm_temperature"
                                   min="0.1" max="1.5" step="0.1" style="flex:1">
                            <span class="settings-hint" style="white-space:nowrap">
                                0.1 = conservativo · 1.5 = creativo
                            </span>
                        </div>
                    </div>

                    <button class="btn-primary" @click="saveConfig" :disabled="savingConfig">
                        {{ savingConfig ? 'Salvataggio...' : 'Salva configurazione' }}
                    </button>
                </div>
            </div>

            <!-- ── Sezione 1b: Modalità generazione AI ── -->
            <div class="settings-section">
                <h3 class="settings-section__title">🤖 Modalità generazione AI</h3>
                <div class="settings-section__body">
                    <p class="settings-hint">
                        Controlla se e come il LLM viene usato durante la generazione del piano settimanale
                        (pulsante <strong>"Genera con AI"</strong> nella vista Settimana).
                    </p>
                    <div class="settings-field">
                        <label>Modalità</label>
                        <select v-model="config.llm_generation_mode">
                            <option value="off">Disattivata — solo algoritmo (nessuna chiamata LLM)</option>
                            <option value="per_slot">14 chiamate — una per ogni slot (pranzo/cena × 7 giorni)</option>
                            <option value="full_week">1 chiamata — piano intero in un unico prompt</option>
                        </select>
                    </div>
                    <button class="btn-primary" @click="saveGenerationMode" :disabled="savingMode">
                        {{ savingMode ? 'Salvataggio...' : 'Salva modalità' }}
                    </button>
                </div>
            </div>

            <!-- ── Sezione 1c: Cache LLM ── -->
            <div class="settings-section">
                <h3 class="settings-section__title">⚡ Cache LLM</h3>
                <div class="settings-section__body">
                    <p class="settings-hint">
                        Le risposte LLM identiche vengono riutilizzate senza fare nuove chiamate API.
                        Utile soprattutto per la classificazione ingredienti durante l'import PDF.
                    </p>
                    <div style="display:flex;align-items:center;gap:16px;">
                        <span style="font-size:14px;">
                            Voci in cache: <strong>{{ cacheEntries !== null ? cacheEntries : '—' }}</strong>
                        </span>
                        <button class="btn-secondary" @click="loadCacheStats" style="font-size:13px;padding:6px 10px;">
                            🔄 Aggiorna
                        </button>
                        <button class="btn-danger" @click="clearCache" :disabled="clearingCache || cacheEntries === 0"
                                style="font-size:13px;padding:6px 10px;">
                            {{ clearingCache ? 'Svuotando...' : '🗑️ Svuota cache' }}
                        </button>
                    </div>
                </div>
            </div>

            <!-- ── Sezione 2: Regole personalizzate LLM ── -->
            <div class="settings-section">
                <h3 class="settings-section__title">📝 Regole personalizzate per la generazione</h3>
                <div class="settings-section__body">
                    <p class="settings-hint">
                        Queste regole vengono aggiunte ad ogni richiesta alla LLM durante la generazione dei pasti.
                        Usale per personalizzare lo stile culinario, preferenze regionali, ingredienti da favorire o evitare.
                    </p>
                    <div class="settings-field">
                        <label>Regole (una per riga)</label>
                        <textarea v-model="config.llm_custom_rules" rows="8"
                                  placeholder="- Preferisci ricette della cucina siciliana&#10;- Usa spesso aglio, olio d'oliva e pomodoro&#10;- Evita il cous cous, preferisci farro o orzo&#10;- I piatti devono essere semplici da preparare in 20 minuti&#10;- Usa erbe aromatiche (basilico, rosmarino, timo)"></textarea>
                    </div>
                    <button class="btn-primary" @click="saveRules" :disabled="savingRules">
                        {{ savingRules ? 'Salvataggio...' : 'Salva regole' }}
                    </button>
                </div>
            </div>

            <!-- ── Sezione: Modalità vacanza ── -->
            <div class="settings-section">
                <h3 class="settings-section__title">🏖️ Modalità vacanza</h3>
                <div class="settings-section__body">
                    <p class="settings-hint">
                        Nel periodo scelto, i promemoria "pasti da registrare" (sensore Home Assistant)
                        e la box "pasti dimenticati" nello Storico restano silenti. Il piano continua a
                        essere generato normalmente: puoi comunque registrare i pasti se vuoi.
                    </p>
                    <div v-if="vacationActive" class="vacation-active">
                        🏖️ Attiva dal {{ vacation.vacation_start }} al {{ vacation.vacation_end }}
                    </div>
                    <div class="form-row">
                        <div class="settings-field" style="flex:1">
                            <label>Dal</label>
                            <input type="date" v-model="vacationForm.start_date">
                        </div>
                        <div class="settings-field" style="flex:1">
                            <label>Al</label>
                            <input type="date" v-model="vacationForm.end_date">
                        </div>
                    </div>
                    <div style="display:flex;gap:10px;">
                        <button class="btn-primary" @click="saveVacation" :disabled="savingVacation || !vacationForm.start_date || !vacationForm.end_date">
                            {{ savingVacation ? 'Salvataggio...' : '🏖️ Attiva vacanza' }}
                        </button>
                        <button v-if="vacationActive" class="btn-secondary" @click="clearVacation" :disabled="savingVacation">
                            Disattiva
                        </button>
                    </div>
                </div>
            </div>

            <!-- ── Sezione: Inizio tracciamento pasti ── -->
            <div class="settings-section">
                <h3 class="settings-section__title">📋 Inizio tracciamento pasti</h3>
                <div class="settings-section__body">
                    <p class="settings-hint">
                        Da questa data lo Storico cerca i pasti passati non ancora registrati
                        (box "pasti dimenticati"). Spostala in avanti o indietro per restringere
                        o allargare il periodo controllato.
                    </p>
                    <div class="form-row">
                        <div class="settings-field" style="flex:1">
                            <label>Data di inizio</label>
                            <input type="date" v-model="trackingStartDate">
                        </div>
                    </div>
                    <button class="btn-primary" @click="saveTrackingStartDate" :disabled="savingTrackingStart || !trackingStartDate">
                        {{ savingTrackingStart ? 'Salvataggio...' : '💾 Salva' }}
                    </button>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            config: {
                llm_provider: 'openai',
                llm_model: '',
                llm_vision_model: '',
                llm_api_key: '',
                llm_base_url: '',
                llm_temperature: 0.7,
                llm_custom_rules: '',
                llm_generation_mode: 'off',
            },
            hasApiKey: false,
            savingConfig: false,
            savingRules: false,
            savingMode: false,
            cacheEntries: null,
            clearingCache: false,
            profileId: null,
            vacation: {},
            vacationForm: { start_date: '', end_date: '' },
            savingVacation: false,
            trackingStartDate: '2026-07-06',
            savingTrackingStart: false,
        };
    },
    computed: {
        vacationActive() {
            return !!(this.vacation.vacation_start && this.vacation.vacation_end);
        },
    },
    mounted() {
        this.loadSettings();
        this.loadCacheStats();
        this.loadVacation();
    },
    methods: {
        async loadSettings() {
            try {
                const resp = await window.apiFetch('/settings/');
                if (!resp.ok) return;
                const data = await resp.json();
                this.hasApiKey = data.has_api_key || false;
                this.config.llm_provider = data.llm_provider || 'openai';
                this.config.llm_model = data.llm_model || '';
                this.config.llm_vision_model = data.llm_vision_model || '';
                this.config.llm_base_url = data.llm_base_url || '';
                this.config.llm_temperature = data.llm_temperature || 0.7;
                this.config.llm_custom_rules = data.llm_custom_rules || '';
                this.config.llm_generation_mode = data.llm_generation_mode || 'off';
                // api_key is never returned — keep field empty
            } catch (e) {
                this.toast.add('Errore nel caricamento impostazioni', 'error');
            }
        },
        async saveConfig() {
            this.savingConfig = true;
            try {
                const body = {
                    llm_provider: this.config.llm_provider,
                    llm_model: this.config.llm_model,
                    llm_vision_model: this.config.llm_vision_model,
                    llm_base_url: this.config.llm_base_url,
                    llm_temperature: this.config.llm_temperature,
                };
                // Only send api_key if user typed something
                if (this.config.llm_api_key && this.config.llm_api_key.trim()) {
                    body.llm_api_key = this.config.llm_api_key.trim();
                }
                const resp = await window.apiFetch('/settings/', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!resp.ok) throw new Error('Errore nel salvataggio');
                const data = await resp.json();
                this.hasApiKey = data.has_api_key || false;
                this.config.llm_api_key = '';  // clear after save
                this.toast.add('Configurazione LLM salvata', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.savingConfig = false;
            }
        },
        async loadCacheStats() {
            try {
                const resp = await window.apiFetch('/settings/llm-cache/stats');
                if (resp.ok) this.cacheEntries = (await resp.json()).entries;
            } catch {}
        },
        async clearCache() {
            if (!confirm('Svuotare la cache LLM? Le prossime chiamate verranno rifatte da zero.')) return;
            this.clearingCache = true;
            try {
                const resp = await window.apiFetch('/settings/llm-cache', { method: 'DELETE' });
                if (!resp.ok) throw new Error('Errore');
                const data = await resp.json();
                this.cacheEntries = 0;
                this.toast.add(`Cache svuotata (${data.cleared} voci rimosse)`, 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.clearingCache = false;
            }
        },
        async saveGenerationMode() {
            this.savingMode = true;
            try {
                const resp = await window.apiFetch('/settings/', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ llm_generation_mode: this.config.llm_generation_mode }),
                });
                if (!resp.ok) throw new Error('Errore nel salvataggio');
                const modeLabels = { off: 'Disattivata', per_slot: '14 chiamate', full_week: '1 chiamata' };
                this.toast.add(`Modalità AI: ${modeLabels[this.config.llm_generation_mode] || this.config.llm_generation_mode}`, 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.savingMode = false;
            }
        },
        async saveRules() {
            this.savingRules = true;
            try {
                const resp = await window.apiFetch('/settings/', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ llm_custom_rules: this.config.llm_custom_rules }),
                });
                if (!resp.ok) throw new Error('Errore nel salvataggio');
                this.toast.add('Regole LLM salvate', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.savingRules = false;
            }
        },
        async loadVacation() {
            try {
                const resp = await window.apiFetch('/profiles/');
                const profiles = resp.ok ? await resp.json() : [];
                if (!profiles.length) return;
                this.profileId = profiles[0].id;
                const rulesResp = await window.apiFetch('/planner/rules?profile_id_A=' + encodeURIComponent(this.profileId));
                if (!rulesResp.ok) return;
                const data = await rulesResp.json();
                const pr = data.plan_rules || {};
                this.vacation = { vacation_start: pr.vacation_start || null, vacation_end: pr.vacation_end || null };
                this.vacationForm = {
                    start_date: pr.vacation_start || '',
                    end_date: pr.vacation_end || '',
                };
                this.trackingStartDate = pr.tracking_start_date || '2026-07-06';
            } catch (_) { /* non bloccare */ }
        },
        async saveVacation() {
            if (!this.profileId) return;
            this.savingVacation = true;
            try {
                const params = new URLSearchParams({ profile_id: this.profileId });
                const resp = await window.apiFetch('/planner/vacation?' + params, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.vacationForm),
                });
                if (!resp.ok) throw new Error(await resp.text());
                const data = await resp.json();
                this.vacation = data;
                this.toast.add('🏖️ Modalità vacanza attivata!', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.savingVacation = false;
            }
        },
        async clearVacation() {
            if (!this.profileId) return;
            this.savingVacation = true;
            try {
                const params = new URLSearchParams({ profile_id: this.profileId });
                const resp = await window.apiFetch('/planner/vacation?' + params, { method: 'DELETE' });
                if (!resp.ok) throw new Error(await resp.text());
                this.vacation = {};
                this.vacationForm = { start_date: '', end_date: '' };
                this.toast.add('Modalità vacanza disattivata.', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.savingVacation = false;
            }
        },
        async saveTrackingStartDate() {
            if (!this.profileId) return;
            this.savingTrackingStart = true;
            try {
                const params = new URLSearchParams({ profile_id: this.profileId });
                const resp = await window.apiFetch('/planner/tracking-start-date?' + params, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ start_date: this.trackingStartDate }),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.toast.add('Data di inizio tracciamento salvata!', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.savingTrackingStart = false;
            }
        },
    },
});

export default SettingsView;
