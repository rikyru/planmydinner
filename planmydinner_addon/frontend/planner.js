import { defineComponent } from 'vue';

const WeekView = defineComponent({
    name: 'WeekView',
    inject: ['toast'],
    template: `
        <div class="week-layout" @click="closeMealMenu">

            <!-- ── Sidebar ────────────────────────────────────────────── -->
            <aside class="week-sidebar">
                <h2 class="sidebar-title">Settimana</h2>

                <div class="sidebar-field">
                    <label class="sidebar-label">Dal</label>
                    <input type="date" v-model="startDate" @change="onStartDateChange" />
                    <span class="sidebar-range">→ {{ endDateLabel }}</span>
                </div>

                <div class="sidebar-actions">
                    <button @click.stop="goToToday" class="btn-today sidebar-btn">Oggi</button>
                    <template v-if="!loading && profiles.length >= 2">
                        <button @click.stop="generateWeek(false)" :disabled="generating"
                                class="btn-regenerate sidebar-btn">
                            {{ generating ? 'Generando...' : 'Rigenera' }}
                        </button>
                        <button @click.stop="generateWithAI" :disabled="generating"
                                class="btn-ai sidebar-btn"
                                title="Genera il piano usando il LLM (modalità configurabile in Impostazioni)">
                            {{ generating ? 'Generando...' : '🤖 Genera con AI' }}
                        </button>
                        <button @click.stop="generateWeek(true)" :disabled="generating"
                                class="btn-fantasy sidebar-btn"
                                title="Usa LLM per inventare ricette creative ad ogni slot">
                            {{ generating ? 'Generando...' : '✨ ExtraFantasy' }}
                        </button>
                        <button @click.stop="openDebugModal" class="btn-secondary sidebar-btn"
                                title="Log LLM e trace generazione piano">
                            🐛 Debug
                        </button>
                    </template>
                </div>

                <div v-if="loading" class="loading" style="margin-top:16px">Caricamento...</div>
                <div v-if="error" class="error-box" style="margin-top:12px">{{ error }}</div>
                <div v-if="!loading && profiles.length < 2" class="hint" style="margin-top:12px">
                    Crea almeno 2 profili per usare il pianificatore.
                </div>
            </aside>

            <!-- ── Area principale ───────────────────────────────────── -->
            <div class="week-main">

                <!-- Nessun piano -->
                <div v-if="!loading && profiles.length >= 2 && !weekPlan && !error" class="no-plan">
                    <p>Nessun piano per questa settimana.</p>
                    <div style="display:flex; gap:8px; flex-wrap:wrap;">
                        <button @click.stop="generateWeek(false)" :disabled="generating" class="btn-primary">
                            {{ generating ? 'Generazione...' : 'Genera piano 7 giorni' }}
                        </button>
                        <button @click.stop="generateWithAI" :disabled="generating" class="btn-ai"
                                title="Genera il piano usando il LLM (modalità configurabile in Impostazioni)">
                            {{ generating ? 'Generando...' : '🤖 Genera con AI' }}
                        </button>
                        <button @click.stop="generateWeek(true)" :disabled="generating" class="btn-fantasy"
                                title="Usa LLM per inventare ricette creative ad ogni slot">
                            {{ generating ? 'Generando...' : '✨ ExtraFantasy' }}
                        </button>
                    </div>
                </div>

                <!-- Griglia giorni -->
                <div v-if="weekPlan" class="week-grid">
                    <article v-for="day in weekPlan" :key="day.date"
                             class="day-card" :class="{ 'day-card--today': isToday(day.date) }">

                        <header class="day-card__header">
                            <div class="day-card__names">
                                <span class="day-name">{{ formatDayName(day.date) }}</span>
                                <span class="day-date">{{ formatShortDate(day.date) }}</span>
                            </div>
                            <span v-if="isToday(day.date)" class="today-badge">Oggi</span>
                        </header>

                        <div class="day-card__meals">
                            <template v-if="day.meals && day.meals.length > 0">
                                <div v-for="meal in day.meals" :key="meal.meal_type"
                                     class="meal-row"
                                     :class="{ 'meal-row--not-eaten': isNotEaten(meal), 'meal-row--free': isFree(meal) }">
                                    <div class="meal-row__info" @click.stop="openMealModal(day.date, meal)">
                                        <span class="meal-row__icon">{{ meal.meal_type === 'pranzo' ? '☀️' : '🌙' }}</span>
                                        <span class="meal-row__type">{{ meal.meal_type === 'pranzo' ? 'Pranzo' : 'Cena' }}</span>
                                        <span v-if="isNotEaten(meal)" class="meal-badge meal-badge--not-eaten">✗</span>
                                        <span v-else-if="isFree(meal)" class="meal-badge meal-badge--free">🎉</span>
                                        <span class="meal-row__name">{{ meal.items?.[0]?.item_name || '—' }}</span>
                                    </div>
                                    <div class="meal-row__menu-wrap">
                                        <span v-if="fantasyApplying === day.date + '_' + meal.meal_type"
                                              class="fantasy-spinner" title="ExtraFantasy in corso...">✨</span>
                                        <button v-else class="btn-meal-menu"
                                                @click.stop="toggleMealMenu(day.date, meal.meal_type)"
                                                :aria-label="'Azioni ' + meal.meal_type">⋯</button>
                                        <div v-if="activeMealMenu === day.date + '_' + meal.meal_type"
                                             class="meal-menu" @click.stop>
                                            <button v-if="meal.items?.[0]?.recipe_id"
                                                    @click="menuOpenComponent(day.date, meal, 'carb')">↕ Carboidrato</button>
                                            <button v-if="meal.items?.[0]?.recipe_id"
                                                    @click="menuOpenComponent(day.date, meal, 'protein')">↕ Proteina</button>
                                            <button v-if="meal.items?.[0]?.recipe_id"
                                                    @click="menuOpenComponent(day.date, meal, 'veg')">↕ Verdura</button>
                                            <button class="meal-menu__change"
                                                    @click="menuChangeRecipe(day.date, meal.meal_type)">↺ Cambia ricetta</button>
                                            <button class="meal-menu__fantasy"
                                                    @click="applyFantasySlot(day.date, meal.meal_type)">✨ ExtraFantasy</button>
                                        </div>
                                    </div>
                                </div>
                            </template>
                            <div v-else class="no-meals">Nessun pasto pianificato</div>
                        </div>
                    </article>
                </div>
            </div>

            <!-- ── Modal pasto (click su meal-row__info) ─────────────── -->
            <div v-if="showMealModal" class="modal-overlay" @click.self="closeMealModal">
                <div class="modal">
                    <h3>
                        {{ mealModalMeal?.meal_type === 'pranzo' ? '☀️' : '🌙' }}
                        {{ mealModalMeal?.meal_type === 'pranzo' ? 'Pranzo' : 'Cena' }}
                        <span style="font-weight:400; font-size:14px; color:#868e96">
                            — {{ formatDateLabel(mealModalDate) }}
                        </span>
                    </h3>

                    <!-- Vista ricetta -->
                    <div v-if="mealRecipeDetail">
                        <div style="display:flex; align-items:center; gap:10px; margin-bottom:8px;">
                            <button @click="mealRecipeDetail = null" class="btn-secondary">← Nascondi</button>
                            <span style="font-size:13px; color:#555;">
                                {{ mealRecipeDetail.total_time_minutes }} min · {{ mealRecipeDetail.difficulty }}
                            </span>
                        </div>
                        <p style="font-weight:600; font-size:15px; margin:0 0 6px; color:#212529;">
                            {{ mealRecipeDetail.name }}
                        </p>
                        <p v-if="mealRecipeDetail.description" style="font-size:13px; color:#495057; margin:0 0 12px;">
                            {{ mealRecipeDetail.description }}
                        </p>
                        <h4 style="margin:0 0 8px; font-size:14px;">Ingredienti</h4>
                        <ul class="recipe-detail-list">
                            <li v-for="ing in flatIngredients" :key="ing.name">
                                <span>{{ ing.name }}</span>
                                <span class="recipe-detail-grams">{{ ing.grams }}g</span>
                            </li>
                        </ul>
                        <div v-if="mealRecipeDetail.steps && mealRecipeDetail.steps.length > 0">
                            <h4 style="margin:12px 0 8px; font-size:14px;">Preparazione</h4>
                            <ol class="recipe-detail-steps">
                                <li v-for="step in mealRecipeDetail.steps" :key="step">{{ step }}</li>
                            </ol>
                        </div>
                    </div>

                    <!-- Vista principale -->
                    <div v-else-if="!mealModalComponent">
                        <p style="font-weight:600; margin:8px 0 12px; font-size:15px;">
                            {{ mealModalMeal?.items?.[0]?.item_name || '—' }}
                        </p>

                        <!-- Azioni componenti (solo per pasti normali con recipe_id) -->
                        <template v-if="mealModalMeal?.items?.[0]?.recipe_id && !isNotEaten(mealModalMeal) && !isFree(mealModalMeal)">
                            <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px;">
                                <button @click="openMealComponent('carb')" class="btn-swap">↕ Carbo</button>
                                <button @click="openMealComponent('protein')" class="btn-swap">↕ Proteina</button>
                                <button @click="openMealComponent('veg')" class="btn-swap">↕ Verdura</button>
                            </div>
                        </template>

                        <!-- Azioni cambio ricetta (solo per pasti normali) -->
                        <template v-if="!isNotEaten(mealModalMeal) && !isFree(mealModalMeal)">
                            <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px;">
                                <button @click="openChangeFromMeal" class="btn-secondary">↺ Cambia ricetta</button>
                                <button @click="applyFantasySlot(mealModalDate, mealModalMeal.meal_type, true)"
                                        :disabled="mealModalApplying" class="btn-fantasy" style="font-size:13px; padding:7px 12px;">
                                    {{ mealModalApplying ? '✨...' : '✨ ExtraFantasy' }}
                                </button>
                                <button @click="mealModalComponent = 'custom'" class="btn-secondary">✏️ Personalizzato</button>
                            </div>
                            <div v-if="mealModalMeal?.items?.[0]?.recipe_id" style="margin-bottom:10px;">
                                <button @click="loadRecipeDetail" :disabled="loadingRecipe" class="btn-secondary">
                                    {{ loadingRecipe ? 'Caricamento...' : '📋 Vedi ricetta' }}
                                </button>
                            </div>
                        </template>

                        <!-- Azioni per pasti passati -->
                        <template v-if="isPast(mealModalDate)">
                            <hr style="border:none; border-top:1px solid #dee2e6; margin:10px 0;">

                            <!-- Pasto già segnato come non mangiato -->
                            <div v-if="isNotEaten(mealModalMeal)" style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                                <span class="meal-status-badge meal-status-badge--not-eaten">✗ Non mangiato</span>
                                <button @click="cancelNotEaten" class="btn-secondary">↩ Ripristina slot</button>
                            </div>

                            <!-- Pasto già segnato come pasto libero -->
                            <div v-else-if="isFree(mealModalMeal)" style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                                <span class="meal-status-badge meal-status-badge--free">🎉 Pasto libero</span>
                                <button @click="cancelFreeMealFromWeek" class="btn-secondary">↩ Ripristina slot</button>
                            </div>

                            <!-- Pasto normale passato: mostra opzioni -->
                            <div v-else>
                                <div v-if="!showFreeMealInput" style="display:flex; gap:8px; flex-wrap:wrap;">
                                    <button @click="markNotEaten" :disabled="mealModalApplying" class="btn-not-eaten">
                                        {{ mealModalApplying ? '...' : '✗ Non mangiato' }}
                                    </button>
                                    <button @click="openFreeMealInput" class="btn-secondary">🎉 Pasto libero</button>
                                </div>
                                <div v-else style="display:flex; gap:8px; align-items:center; margin-top:6px; flex-wrap:wrap;">
                                    <input v-model="freeMealModalTitle" type="text"
                                           placeholder="Cosa hai mangiato? (opzionale)"
                                           style="flex:1; min-width:160px;"
                                           @keyup.enter="confirmFreeMeal" />
                                    <button @click="confirmFreeMeal" :disabled="mealModalApplying" class="btn-primary">
                                        {{ mealModalApplying ? '...' : 'OK' }}
                                    </button>
                                    <button @click="showFreeMealInput = false" class="btn-secondary">Annulla</button>
                                </div>
                            </div>
                        </template>

                        <div v-if="mealModalError" class="error-box" style="margin-top:10px">{{ mealModalError }}</div>
                    </div>

                    <!-- Vista alternativa componente -->
                    <div v-else-if="mealModalComponent !== 'custom'">
                        <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">
                            <button @click="mealModalComponent = null; mealModalOptions = []" class="btn-secondary">← Indietro</button>
                            <span style="font-size:14px; color:#555;">
                                Cambia {{ mealModalComponent === 'carb' ? 'carboidrato' : mealModalComponent === 'protein' ? 'proteina' : 'verdura' }}
                            </span>
                        </div>
                        <div v-if="mealModalApplying" class="loading">Caricamento...</div>
                        <div v-if="mealModalError" class="error-box">{{ mealModalError }}</div>
                        <div v-for="option in mealModalOptions" :key="option.option_id"
                             class="recipe-option" @click="applyMealOption(option.recipe_id)">
                            <strong>{{ option.name }}</strong>
                            <span>{{ option.total_time_minutes }} min · {{ option.difficulty }}</span>
                            <span v-if="option.key_ingredients && option.key_ingredients.length">
                                {{ option.key_ingredients.join(', ') }}
                            </span>
                        </div>
                        <div v-if="!mealModalApplying && !mealModalError && mealModalOptions.length === 0" class="hint">
                            Nessuna alternativa trovata.
                        </div>
                    </div>

                    <!-- Vista pasto personalizzato -->
                    <div v-else>
                        <div style="display:flex; align-items:center; gap:10px; margin-bottom:16px;">
                            <button @click="mealModalComponent = null" class="btn-secondary">← Indietro</button>
                            <span style="font-size:14px; color:#555;">Inserisci pasto manualmente</span>
                        </div>
                        <div v-if="mealModalError" class="error-box" style="margin-bottom:12px">{{ mealModalError }}</div>
                        <div class="custom-meal-form">
                            <div class="custom-meal-field">
                                <label>Nome pasto</label>
                                <input v-model="customMeal.title" placeholder="es. Pasta al pomodoro" @keyup.enter="submitCustomMeal" />
                            </div>
                            <div class="custom-meal-row">
                                <div class="custom-meal-field">
                                    <label>🌾 Carboidrato</label>
                                    <input v-model="customMeal.carb_name" placeholder="es. pasta" />
                                </div>
                                <div class="custom-meal-field custom-meal-field--sm">
                                    <label>Grammi</label>
                                    <input v-model.number="customMeal.carb_grams" type="number" min="0" placeholder="80" />
                                </div>
                            </div>
                            <div class="custom-meal-row">
                                <div class="custom-meal-field">
                                    <label>🥩 Proteina</label>
                                    <input v-model="customMeal.protein_name" placeholder="es. pollo" />
                                </div>
                                <div class="custom-meal-field custom-meal-field--sm">
                                    <label>Grammi</label>
                                    <input v-model.number="customMeal.protein_grams" type="number" min="0" placeholder="120" />
                                </div>
                            </div>
                            <div class="custom-meal-row">
                                <div class="custom-meal-field">
                                    <label>🥦 Verdura <span style="color:#adb5bd">(opzionale)</span></label>
                                    <input v-model="customMeal.veg_name" placeholder="es. zucchine" />
                                </div>
                                <div class="custom-meal-field custom-meal-field--sm">
                                    <label>Grammi</label>
                                    <input v-model.number="customMeal.veg_grams" type="number" min="0" placeholder="150" />
                                </div>
                            </div>
                            <div class="custom-meal-field">
                                <label>Note <span style="color:#adb5bd">(opzionale)</span></label>
                                <input v-model="customMeal.notes" placeholder="cottura, variante, ecc." />
                            </div>
                        </div>
                        <button @click="submitCustomMeal" :disabled="mealModalApplying"
                                class="btn-primary" style="margin-top:14px; width:100%">
                            {{ mealModalApplying ? 'Salvataggio...' : '✓ Salva pasto' }}
                        </button>
                    </div>

                    <button @click="closeMealModal" class="btn-secondary" style="margin-top:14px">Chiudi</button>
                </div>
            </div>

            <!-- ── Modal debug ────────────────────────────────────────── -->
            <div v-if="showDebugModal" class="modal-overlay" @click.self="closeDebugModal">
                <div class="modal" style="max-width:860px; width:98vw; max-height:90vh; overflow-y:auto;">
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
                        <h3 style="margin:0;">🐛 Debug generazione piano</h3>
                        <button @click="closeDebugModal" class="btn-secondary" style="padding:4px 10px;">✕</button>
                    </div>

                    <!-- Tabs -->
                    <div style="display:flex; gap:6px; margin-bottom:14px; border-bottom:2px solid #dee2e6; padding-bottom:6px;">
                        <button @click="debugTab='status'"
                                :style="debugTab==='status' ? 'font-weight:700;border-bottom:2px solid #339af0;color:#1971c2;' : 'color:#495057;'"
                                style="background:none;border:none;cursor:pointer;font-size:14px;padding:4px 8px;">
                            📋 Stato sistema
                        </button>
                        <button @click="debugTab='trace'"
                                :style="debugTab==='trace' ? 'font-weight:700;border-bottom:2px solid #339af0;color:#1971c2;' : 'color:#495057;'"
                                style="background:none;border:none;cursor:pointer;font-size:14px;padding:4px 8px;">
                            🗓️ Trace generazione
                        </button>
                        <button @click="debugTab='llm'"
                                :style="debugTab==='llm' ? 'font-weight:700;border-bottom:2px solid #339af0;color:#1971c2;' : 'color:#495057;'"
                                style="background:none;border:none;cursor:pointer;font-size:14px;padding:4px 8px;">
                            🤖 Log LLM
                        </button>
                    </div>

                    <div v-if="debugLoading" class="loading">Caricamento dati debug...</div>

                    <!-- Tab: Stato sistema -->
                    <div v-else-if="debugTab==='status'">
                        <div v-if="!debugStatus" class="hint">Nessun dato. Apri il debug per caricare.</div>
                        <template v-else>

                            <!-- Path generazione -->
                            <div style="margin-bottom:14px; padding:10px 14px; border-radius:8px;"
                                 :style="debugStatus.generation_path==='none' ? 'background:#fff5f5;border:1px solid #ffc9c9;' :
                                         debugStatus.generation_path==='plan_rules' ? 'background:#ebfbee;border:1px solid #b2f2bb;' :
                                         'background:#fff9db;border:1px solid #ffec99;'">
                                <strong>Path di generazione:</strong>
                                <span style="margin-left:8px; font-size:14px;"
                                      :style="debugStatus.generation_path==='none' ? 'color:#c92a2a;' :
                                              debugStatus.generation_path==='plan_rules' ? 'color:#2f9e44;' : 'color:#e67700;'">
                                    {{ debugStatus.generation_path === 'plan_rules' ? '✅ PlanRules (importato da PDF)' :
                                       debugStatus.generation_path === 'legacy'     ? '⚠️ Legacy StructuredMealPlan' :
                                                                                      '❌ Nessun piano — generazione impossibile' }}
                                </span>
                            </div>

                            <!-- PlanRules -->
                            <div style="margin-bottom:14px;">
                                <strong style="font-size:13px;">📐 PlanRules</strong>
                                <div v-if="!debugStatus.plan_rules" style="color:#868e96; font-size:13px; margin-top:4px;">
                                    Non trovate. Importa un piano PDF prima di generare.
                                </div>
                                <div v-else style="font-size:12px; margin-top:6px; display:grid; grid-template-columns:1fr 1fr; gap:6px;">
                                    <div style="background:#f8f9fa; border-radius:6px; padding:8px;">
                                        <div style="color:#868e96; font-size:11px; margin-bottom:4px;">Importato</div>
                                        <div>{{ debugStatus.plan_rules.imported_at?.slice(0,16).replace('T',' ') }}</div>
                                    </div>
                                    <div style="background:#f8f9fa; border-radius:6px; padding:8px;">
                                        <div style="color:#868e96; font-size:11px; margin-bottom:4px;">Frequenze proteiche</div>
                                        <div v-if="!debugStatus.plan_rules.frequency_targets || Object.keys(debugStatus.plan_rules.frequency_targets).length===0" style="color:#c92a2a;">
                                            ⚠️ Nessuna — planner non sa come distribuire proteine
                                        </div>
                                        <div v-for="(tgt, cat) in debugStatus.plan_rules.frequency_targets" :key="cat">
                                            <strong>{{ cat }}</strong>: {{ tgt.min }}–{{ tgt.max }}x/sett
                                            <span v-if="tgt.hard_max"> (hard max {{ tgt.hard_max }})</span>
                                        </div>
                                    </div>
                                    <div style="background:#f8f9fa; border-radius:6px; padding:8px;">
                                        <div style="color:#868e96; font-size:11px; margin-bottom:4px;">Carbo target (g)</div>
                                        <div v-for="(v, k) in debugStatus.plan_rules.carb_target" :key="k">{{ k }}: {{ v }}g</div>
                                        <div v-if="!debugStatus.plan_rules.carb_target" style="color:#c92a2a;">⚠️ Non impostato</div>
                                    </div>
                                    <div style="background:#f8f9fa; border-radius:6px; padding:8px;">
                                        <div style="color:#868e96; font-size:11px; margin-bottom:4px;">Proteina target (g)</div>
                                        <div v-for="(v, k) in debugStatus.plan_rules.protein_target" :key="k">{{ k }}: {{ v }}g</div>
                                        <div v-if="!debugStatus.plan_rules.protein_target" style="color:#c92a2a;">⚠️ Non impostato</div>
                                    </div>
                                </div>
                            </div>

                            <!-- Sequenza proteica -->
                            <div style="margin-bottom:14px;">
                                <strong style="font-size:13px;">🔗 Sequenza proteica (14 slot)</strong>
                                <div v-if="!debugStatus.protein_sequence_14?.length" style="color:#868e96; font-size:13px; margin-top:4px;">
                                    Non calcolabile (mancano frequency_targets).
                                </div>
                                <div v-else style="display:flex; flex-wrap:wrap; gap:4px; margin-top:6px;">
                                    <template v-for="(cat, i) in debugStatus.protein_sequence_14" :key="i">
                                        <div style="font-size:11px; padding:3px 7px; border-radius:4px; background:#e7f5ff; color:#1971c2;">
                                            <span style="color:#868e96;">{{ i%2===0 ? '🌞' : '🌙' }}{{ Math.floor(i/2)+1 }}</span>
                                            {{ cat || '—' }}
                                        </div>
                                    </template>
                                </div>
                            </div>

                            <!-- Pool ricette -->
                            <div style="margin-bottom:14px;">
                                <strong style="font-size:13px;">📚 Pool ricette</strong>
                                <div style="display:flex; gap:10px; margin-top:6px; flex-wrap:wrap;">
                                    <div style="background:#f8f9fa; border-radius:6px; padding:8px 12px; font-size:12px;">
                                        Totale: <strong :style="debugStatus.recipe_pool.total < 5 ? 'color:#c92a2a;' : 'color:#2f9e44;'">
                                            {{ debugStatus.recipe_pool.total }}
                                        </strong>
                                        <span v-if="debugStatus.recipe_pool.total < 5" style="color:#c92a2a;"> ⚠️ Troppo poche — usa seed o bulk import</span>
                                    </div>
                                    <div style="background:#f8f9fa; border-radius:6px; padding:8px 12px; font-size:12px;">
                                        Manuali: <strong>{{ debugStatus.recipe_pool.manual }}</strong>
                                        <span style="color:#868e96;"> (+1.5 boost)</span>
                                    </div>
                                    <div v-for="(n, diff) in debugStatus.recipe_pool.by_difficulty" :key="diff"
                                         style="background:#f8f9fa; border-radius:6px; padding:8px 12px; font-size:12px;">
                                        {{ diff }}: {{ n }}
                                    </div>
                                </div>
                                <details style="margin-top:8px; font-size:12px; color:#495057;">
                                    <summary style="cursor:pointer; color:#1971c2;">Mostra nomi ({{ debugStatus.recipe_pool.names_sample?.length }})</summary>
                                    <div style="margin-top:6px; display:flex; flex-wrap:wrap; gap:4px;">
                                        <span v-for="name in debugStatus.recipe_pool.names_sample" :key="name"
                                              style="background:#f1f3f5; border-radius:4px; padding:2px 6px;">{{ name }}</span>
                                    </div>
                                </details>
                            </div>

                            <!-- Candidate Recipes -->
                            <div style="margin-bottom:14px;">
                                <strong style="font-size:13px;">🧪 CandidateRecipe (generate da LLM)</strong>
                                <div style="display:flex; gap:8px; margin-top:6px; flex-wrap:wrap;">
                                    <div v-if="debugStatus.candidate_recipes.total === 0" style="color:#868e96; font-size:12px;">Nessuna.</div>
                                    <div v-for="(n, status) in debugStatus.candidate_recipes.by_status" :key="status"
                                         style="background:#f8f9fa; border-radius:6px; padding:8px 12px; font-size:12px;">
                                        {{ status }}: <strong>{{ n }}</strong>
                                    </div>
                                </div>
                            </div>

                        </template>
                    </div>

                    <!-- Tab: Trace generazione -->
                    <div v-else-if="debugTab==='trace'">
                        <p v-if="!debugTrace.length" class="hint">Nessun dato. Genera prima un piano.</p>
                        <div v-for="(slot, idx) in debugTrace" :key="idx"
                             style="border:1px solid #dee2e6; border-radius:6px; margin-bottom:8px; overflow:hidden;">
                            <!-- Header riga -->
                            <div @click="debugExpandTrace = debugExpandTrace===idx ? null : idx"
                                 style="display:flex; align-items:center; gap:10px; padding:8px 12px; cursor:pointer; background:#f8f9fa; user-select:none;">
                                <span style="font-size:12px; color:#868e96; min-width:110px;">
                                    {{ formatDateLabel(slot.date) }} · {{ slot.meal_type }}
                                </span>
                                <span style="flex:1; font-weight:500; font-size:13px;" :style="slot.selected_name ? '' : 'color:#e03131;'">
                                    {{ slot.selected_name || slot.error || '— vuoto —' }}
                                </span>
                                <span style="font-size:11px; color:#868e96;">
                                    {{ slot.n_total_recipes }} ricette → {{ slot.n_final_candidates }} candidate
                                </span>
                                <span v-if="slot.target_protein_category"
                                      style="font-size:11px; background:#e7f5ff; color:#1971c2; border-radius:4px; padding:2px 6px;">
                                    {{ slot.target_protein_category }}
                                </span>
                                <span style="color:#adb5bd; font-size:12px;">{{ debugExpandTrace===idx ? '▲' : '▼' }}</span>
                            </div>
                            <!-- Dettaglio espanso -->
                            <div v-if="debugExpandTrace===idx" style="padding:10px 14px; font-size:12px; line-height:1.6;">
                                <div v-if="slot.protein_limit_filtered?.length" style="color:#e03131; margin-bottom:4px;">
                                    ❌ Protein limit: {{ slot.protein_limit_filtered.join(', ') }}
                                </div>
                                <div v-if="slot.used_ids_filtered?.length" style="color:#e67700; margin-bottom:4px;">
                                    🔁 ID già usati: {{ slot.used_ids_filtered.join(', ') }}
                                </div>
                                <div v-if="slot.protein_item_filtered?.length" style="color:#e67700; margin-bottom:4px;">
                                    🔁 Proteina monotona: {{ slot.protein_item_filtered.join(', ') }}
                                </div>
                                <div v-if="slot.protein_cat_excluded?.length" style="color:#862e9c; margin-bottom:4px;">
                                    🚫 Cat. esclusa (pranzo/cena): {{ slot.protein_cat_excluded.join(', ') }}
                                </div>
                                <div v-if="slot.target_protein_narrowed?.length" style="color:#1971c2; margin-bottom:4px;">
                                    🎯 Non-target rimossi: {{ slot.target_protein_narrowed.join(', ') }}
                                </div>
                                <div v-if="slot.scored_recipes?.length" style="margin-top:8px;">
                                    <strong>Top candidate (score):</strong>
                                    <div v-for="r in slot.scored_recipes.slice(0,5)" :key="r.id"
                                         style="display:flex; justify-content:space-between; padding:2px 0; border-bottom:1px solid #f1f3f5;">
                                        <span :style="r.name===slot.selected_name ? 'font-weight:700;color:#2f9e44;' : ''">
                                            {{ r.name === slot.selected_name ? '✓ ' : '' }}{{ r.name }}
                                        </span>
                                        <span style="color:#868e96; min-width:50px; text-align:right;">{{ r.score }}</span>
                                    </div>
                                </div>
                                <div v-if="slot.hard_constraint_fail?.length" style="margin-top:8px; color:#868e96;">
                                    Hard-fail: {{ slot.hard_constraint_fail.slice(0,5).join(', ') }}
                                    <span v-if="slot.hard_constraint_fail.length>5"> +{{ slot.hard_constraint_fail.length-5 }} altri</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Tab: Log LLM -->
                    <div v-else-if="debugTab==='llm'">
                        <p v-if="!debugLlmLog.length" class="hint">Nessuna chiamata LLM registrata.</p>
                        <div v-for="(call, idx) in debugLlmLog" :key="idx"
                             style="border:1px solid #dee2e6; border-radius:6px; margin-bottom:8px; overflow:hidden;">
                            <!-- Header -->
                            <div @click="debugExpandLlm = debugExpandLlm===idx ? null : idx"
                                 style="display:flex; align-items:center; gap:10px; padding:8px 12px; cursor:pointer; background:#f8f9fa; user-select:none;">
                                <span style="font-size:11px; color:#868e96; min-width:80px;">{{ call.timestamp?.slice(11,19) }}</span>
                                <span :style="{
                                    'font-size':'11px','border-radius':'4px','padding':'2px 6px','font-weight':'600',
                                    'background': call.status==='ok' ? '#ebfbee' : call.status==='pending' ? '#f8f9fa' : '#fff5f5',
                                    'color':       call.status==='ok' ? '#2f9e44' : call.status==='pending' ? '#868e96' : '#c92a2a',
                                }">{{ call.status }}</span>
                                <span style="font-size:12px; color:#555; min-width:60px;">{{ call.meal_type }}</span>
                                <span style="flex:1; font-size:13px; font-weight:500;">
                                    {{ call.parsed_name || '(no parse)' }}
                                </span>
                                <span style="font-size:11px; color:#868e96;">
                                    P:{{ call.protein_target_g }}g C:{{ call.carb_target_g }}g
                                    <span v-if="call.target_protein_category"> · {{ call.target_protein_category }}</span>
                                </span>
                                <span style="color:#adb5bd; font-size:12px;">{{ debugExpandLlm===idx ? '▲' : '▼' }}</span>
                            </div>
                            <!-- Dettaglio -->
                            <div v-if="debugExpandLlm===idx" style="padding:10px 14px;">
                                <div style="margin-bottom:10px;">
                                    <strong style="font-size:12px;">Prompt inviato:</strong>
                                    <pre style="font-size:11px; background:#f1f3f5; padding:8px; border-radius:4px; overflow-x:auto; white-space:pre-wrap; max-height:200px; overflow-y:auto; margin:4px 0 0;">{{ call.prompt }}</pre>
                                </div>
                                <div>
                                    <strong style="font-size:12px;">Risposta LLM:</strong>
                                    <pre style="font-size:11px; background:#f1f3f5; padding:8px; border-radius:4px; overflow-x:auto; white-space:pre-wrap; max-height:200px; overflow-y:auto; margin:4px 0 0;">{{ call.raw_response || '(vuota)' }}</pre>
                                </div>
                            </div>
                        </div>
                    </div>

                </div>
            </div>

            <!-- ── Modal cambio ricetta (↺) ──────────────────────────── -->
            <div v-if="showModal" class="modal-overlay" @click.self="closeModal">
                <div class="modal">
                    <h3>Cambia — {{ currentMealType === 'pranzo' ? 'Pranzo' : 'Cena' }}
                        <span style="font-weight:400; font-size:14px; color:#868e96">
                            {{ formatDateLabel(currentDate) }}
                        </span>
                    </h3>
                    <div v-if="loadingOptions" class="loading">Caricamento opzioni...</div>
                    <div v-if="modalError" class="error-box">{{ modalError }}</div>
                    <div v-for="option in recipeOptions" :key="option.option_id"
                         class="recipe-option" @click="applyRecipe(option.recipe_id)">
                        <strong>{{ option.name }}</strong>
                        <span>{{ option.total_time_minutes }} min · {{ option.difficulty }}</span>
                        <span v-if="option.key_ingredients && option.key_ingredients.length">
                            {{ option.key_ingredients.join(', ') }}
                        </span>
                    </div>
                    <div v-if="!loadingOptions && !modalError && recipeOptions.length === 0" class="hint">
                        Nessuna alternativa trovata per questo slot.
                    </div>
                    <button @click="closeModal" class="btn-secondary" style="margin-top:12px">Annulla</button>
                </div>
            </div>

        </div>
    `,
    data() {
        const now = new Date();
        const today = now.toISOString().slice(0, 10);
        // Snap to Monday (0=Sun → 6 days back, 1=Mon → 0, ..., 6=Sat → 5 days back)
        const dayOfWeek = now.getDay(); // 0=Sun
        const daysToMonday = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
        const monday = new Date(now);
        monday.setDate(now.getDate() - daysToMonday);
        const mondayStr = monday.toISOString().slice(0, 10);
        return {
            profiles: [],
            startDate: mondayStr,
            weekPlan: null,
            loading: false,
            error: null,
            generating: false,
            today,
            // Menu ⋯
            activeMealMenu: null,
            // Modal cambio ricetta (↺)
            showModal: false,
            currentDate: null,
            currentMealType: null,
            recipeOptions: [],
            loadingOptions: false,
            modalError: null,
            // Modal pasto (click su meal-row__info)
            showMealModal: false,
            mealModalDate: null,
            mealModalMeal: null,
            mealModalComponent: null,
            mealModalOptions: [],
            mealModalApplying: false,
            mealModalError: null,
            // Form pasto personalizzato
            customMeal: { title: '', protein_name: '', protein_grams: 120, carb_name: '', carb_grams: 80, veg_name: '', veg_grams: 150, notes: '' },
            // ExtraFantasy per singolo slot
            fantasyApplying: null,
            // Non mangiato / Pasto libero (pasti passati)
            freeMealModalTitle: '',
            showFreeMealInput: false,
            // Vista ricetta
            mealRecipeDetail: null,
            loadingRecipe: false,
            // Debug modal
            showDebugModal: false,
            debugTab: 'status',
            debugLoading: false,
            debugStatus: null,
            debugTrace: [],
            debugLlmLog: [],
            debugExpandTrace: null,
            debugExpandLlm: null,
        };
    },
    computed: {
        profileA() { return this.profiles[0] || null; },
        profileB() { return this.profiles[1] || null; },
        endDateLabel() {
            if (!this.startDate) return '';
            const end = new Date(this.startDate + 'T12:00:00');
            end.setDate(end.getDate() + 6);
            return end.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
        },
        flatIngredients() {
            if (!this.mealRecipeDetail) return [];
            const content = this.mealRecipeDetail.content;
            const items = Array.isArray(content) ? content : (content?.components || []);
            return items.map(ing => {
                const qties = ing.quantities || {};
                const key = Object.keys(qties)[0];
                const g = key ? Math.round(qties[key].grams_equiv || qties[key].qty) : '?';
                return { name: ing.name, grams: g };
            });
        },
    },
    mounted() {
        this.loadData();
        this._outsideClick = () => { this.activeMealMenu = null; };
        document.addEventListener('click', this._outsideClick);
    },
    beforeUnmount() {
        document.removeEventListener('click', this._outsideClick);
    },
    methods: {
        // ── Dati ─────────────────────────────────────────────────────────────
        async loadData() {
            this.loading = true;
            this.error = null;
            try {
                const resp = await fetch('/profiles/');
                this.profiles = await resp.json();
                if (this.profiles.length >= 2) await this.loadWeekPlan();
            } catch (e) {
                this.error = 'Errore: ' + e.message;
            } finally {
                this.loading = false;
            }
        },
        async loadWeekPlan() {
            if (!this.profileA) return;
            const params = new URLSearchParams({
                profile_id_A: this.profileA.id,
                profile_id_B: this.profileB?.id || '',
                start_date: this.startDate,
            });
            const resp = await fetch('/planner/weekly-plan?' + params);
            if (resp.ok) {
                this.weekPlan = await resp.json();
            } else if (resp.status === 404) {
                this.weekPlan = null;
            } else {
                this.error = 'Errore nel caricamento del piano.';
            }
        },
        async generateWeek(fantasyMode = false) {
            if (!this.profileA || !this.profileB) return;
            this.generating = true;
            this.error = null;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    current_date: this.startDate,
                    fantasy_mode: fantasyMode,
                });
                const resp = await fetch('/planner/generate-week?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.weekPlan = await resp.json();
                this.toast.add(fantasyMode ? '✨ Piano ExtraFantasy generato!' : 'Piano generato!', 'success');
            } catch (e) {
                this.error = 'Errore: ' + e.message;
            } finally {
                this.generating = false;
            }
        },
        async generateWithAI() {
            if (!this.profileA || !this.profileB) return;
            // Read mode from settings to show appropriate label
            let modeLabel = 'AI';
            try {
                const s = await fetch('/settings/');
                if (s.ok) {
                    const sd = await s.json();
                    const modeMap = { off: 'algoritmo', per_slot: 'AI (14 chiamate)', full_week: 'AI (1 chiamata)' };
                    modeLabel = modeMap[sd.llm_generation_mode] || 'AI';
                    if (sd.llm_generation_mode === 'off') {
                        this.toast.add('Modalità AI disattivata. Attivala in Impostazioni → Modalità generazione AI.', 'error');
                        return;
                    }
                }
            } catch {}

            this.generating = true;
            this.error = null;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    current_date: this.startDate,
                    fantasy_mode: false,
                    // no ai_mode param: backend reads it from AppSettings
                });
                const resp = await fetch('/planner/generate-week?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.weekPlan = await resp.json();
                this.toast.add(`🤖 Piano generato con ${modeLabel}!`, 'success');
            } catch (e) {
                this.error = 'Errore: ' + e.message;
            } finally {
                this.generating = false;
            }
        },

        // ── Menu ⋯ ───────────────────────────────────────────────────────────
        toggleMealMenu(dateStr, mealType) {
            const key = dateStr + '_' + mealType;
            this.activeMealMenu = this.activeMealMenu === key ? null : key;
        },
        closeMealMenu() {
            this.activeMealMenu = null;
        },
        async menuOpenComponent(dateStr, meal, component) {
            this.closeMealMenu();
            this.openMealModal(dateStr, meal);
            await this.openMealComponent(component);
        },
        menuChangeRecipe(dateStr, mealType) {
            this.closeMealMenu();
            this.openChangeModal(dateStr, mealType);
        },
        async applyFantasySlot(dateStr, mealType, fromModal = false) {
            if (!this.profileA || !this.profileB) return;
            this.closeMealMenu();
            if (fromModal) {
                this.mealModalApplying = true;
                this.mealModalError = null;
            } else {
                this.closeMealModal();
                this.fantasyApplying = dateStr + '_' + mealType;
            }
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: mealType,
                    current_date: dateStr,
                });
                const resp = await fetch('/planner/change-recipe?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                const options = await resp.json();
                if (!options.length) throw new Error('Nessuna ricetta trovata dall\'LLM.');
                const applyParams = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: mealType,
                    current_date: dateStr,
                    recipe_id: options[0].recipe_id,
                });
                const applyResp = await fetch('/planner/apply-recipe-option?' + applyParams, { method: 'POST' });
                if (!applyResp.ok) throw new Error(await applyResp.text());
                await this.loadWeekPlan();
                // Auto-apri il modal con il dettaglio della ricetta appena generata
                const day = this.weekPlan.find(d => d.date === dateStr);
                const updatedMeal = day?.meals?.find(m => m.meal_type === mealType);
                if (updatedMeal) {
                    this.openMealModal(dateStr, updatedMeal);
                    await this.loadRecipeDetail();
                }
                this.toast.add('✨ Ricetta ExtraFantasy applicata!', 'success');
            } catch (e) {
                if (fromModal) this.mealModalError = 'Errore: ' + e.message;
                else this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.fantasyApplying = null;
                if (fromModal) this.mealModalApplying = false;
            }
        },

        // ── Modal cambio ricetta (↺) ──────────────────────────────────────
        async openChangeModal(dateStr, mealType) {
            if (!this.profileA || !this.profileB) return;
            this.currentDate = dateStr;
            this.currentMealType = mealType;
            this.recipeOptions = [];
            this.modalError = null;
            this.loadingOptions = true;
            this.showModal = true;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: mealType,
                    current_date: dateStr,
                });
                const resp = await fetch('/planner/change-recipe?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.recipeOptions = await resp.json();
            } catch (e) {
                this.modalError = 'Errore nel caricamento opzioni: ' + e.message;
            } finally {
                this.loadingOptions = false;
            }
        },
        async applyRecipe(recipeId) {
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: this.currentMealType,
                    current_date: this.currentDate,
                    recipe_id: recipeId,
                });
                const resp = await fetch('/planner/apply-recipe-option?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeModal();
                await this.loadWeekPlan();
                this.toast.add('Ricetta aggiornata!', 'success');
            } catch (e) {
                this.modalError = 'Errore: ' + e.message;
            }
        },
        closeModal() {
            this.showModal = false;
            this.currentDate = null;
            this.currentMealType = null;
            this.recipeOptions = [];
            this.modalError = null;
        },

        // ── Modal pasto (click su meal-row__info) ─────────────────────────
        openMealModal(dateStr, meal) {
            this.mealModalDate = dateStr;
            this.mealModalMeal = meal;
            this.mealModalComponent = null;
            this.mealModalOptions = [];
            this.mealModalError = null;
            this.mealRecipeDetail = null;
            this.showFreeMealInput = false;
            this.freeMealModalTitle = '';
            this.showMealModal = true;
        },
        async openMealComponent(component) {
            if (!this.profileA || !this.profileB) return;
            this.mealModalComponent = component;
            this.mealModalOptions = [];
            this.mealModalError = null;
            this.mealModalApplying = true;
            try {
                const recipeId = this.mealModalMeal?.items?.[0]?.recipe_id;
                if (!recipeId) throw new Error('Nessuna ricetta associata a questo pasto.');
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: this.mealModalMeal.meal_type,
                    current_date: this.mealModalDate,
                    recipe_id: recipeId,
                    component,
                });
                const resp = await fetch('/planner/change-component?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.mealModalOptions = await resp.json();
            } catch (e) {
                this.mealModalError = 'Errore: ' + e.message;
            } finally {
                this.mealModalApplying = false;
            }
        },
        async applyMealOption(recipeId) {
            if (!this.profileA || !this.profileB) return;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: this.mealModalMeal.meal_type,
                    current_date: this.mealModalDate,
                    recipe_id: recipeId,
                });
                const resp = await fetch('/planner/apply-recipe-option?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeMealModal();
                await this.loadWeekPlan();
                this.toast.add('Pasto aggiornato!', 'success');
            } catch (e) {
                this.mealModalError = 'Errore: ' + e.message;
            }
        },
        openChangeFromMeal() {
            const dateStr = this.mealModalDate;
            const mealType = this.mealModalMeal?.meal_type;
            this.closeMealModal();
            this.openChangeModal(dateStr, mealType);
        },
        async submitCustomMeal() {
            const c = this.customMeal;
            if (!c.title.trim() || !c.protein_name.trim() || !c.carb_name.trim()) {
                this.mealModalError = 'Nome pasto, proteina e carboidrato sono obbligatori.';
                return;
            }
            if (!this.profileA || !this.profileB) return;
            this.mealModalApplying = true;
            this.mealModalError = null;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: this.mealModalMeal.meal_type,
                    current_date: this.mealModalDate,
                });
                const body = {
                    title: c.title.trim(),
                    protein_name: c.protein_name.trim(),
                    protein_grams: c.protein_grams || 0,
                    carb_name: c.carb_name.trim(),
                    carb_grams: c.carb_grams || 0,
                    veg_name: c.veg_name.trim() || null,
                    veg_grams: c.veg_grams || 150,
                    notes: c.notes.trim(),
                };
                const resp = await fetch('/planner/set-custom-meal?' + params, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeMealModal();
                await this.loadWeekPlan();
                this.toast.add('Pasto salvato!', 'success');
            } catch (e) {
                this.mealModalError = 'Errore: ' + e.message;
            } finally {
                this.mealModalApplying = false;
            }
        },
        closeMealModal() {
            this.showMealModal = false;
            this.mealModalDate = null;
            this.mealModalMeal = null;
            this.mealModalComponent = null;
            this.mealModalOptions = [];
            this.mealModalError = null;
            this.mealRecipeDetail = null;
            this.showFreeMealInput = false;
            this.freeMealModalTitle = '';
            this.customMeal = { title: '', protein_name: '', protein_grams: 120, carb_name: '', carb_grams: 80, veg_name: '', veg_grams: 150, notes: '' };
        },

        // ── Azioni pasti passati ──────────────────────────────────────────
        async markNotEaten() {
            if (!this.profileA) return;
            this.mealModalApplying = true;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB?.id || '',
                    meal_type: this.mealModalMeal.meal_type,
                    current_date: this.mealModalDate,
                });
                const resp = await fetch('/planner/not-eaten?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeMealModal();
                await this.loadWeekPlan();
                this.toast.add('Pasto segnato come non mangiato', 'info');
            } catch (e) {
                this.mealModalError = 'Errore: ' + e.message;
            } finally {
                this.mealModalApplying = false;
            }
        },
        async cancelNotEaten() {
            if (!this.profileA) return;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB?.id || '',
                    meal_type: this.mealModalMeal.meal_type,
                    current_date: this.mealModalDate,
                });
                const resp = await fetch('/planner/not-eaten?' + params, { method: 'DELETE' });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeMealModal();
                await this.loadWeekPlan();
                this.toast.add('Slot ripristinato', 'info');
            } catch (e) {
                this.mealModalError = 'Errore: ' + e.message;
            }
        },
        openFreeMealInput() {
            this.showFreeMealInput = true;
            this.freeMealModalTitle = '';
        },
        async confirmFreeMeal() {
            if (!this.profileA) return;
            this.mealModalApplying = true;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB?.id || '',
                    meal_type: this.mealModalMeal.meal_type,
                    current_date: this.mealModalDate,
                });
                const resp = await fetch('/planner/free-meal?' + params, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: this.freeMealModalTitle.trim() || 'Pasto libero', notes: '' }),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeMealModal();
                await this.loadWeekPlan();
                this.toast.add('🎉 Pasto libero segnato', 'success');
            } catch (e) {
                this.mealModalError = 'Errore: ' + e.message;
            } finally {
                this.mealModalApplying = false;
            }
        },
        async cancelFreeMealFromWeek() {
            if (!this.profileA) return;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB?.id || '',
                    meal_type: this.mealModalMeal.meal_type,
                    current_date: this.mealModalDate,
                });
                const resp = await fetch('/planner/free-meal?' + params, { method: 'DELETE' });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeMealModal();
                await this.loadWeekPlan();
                this.toast.add('Slot ripristinato', 'info');
            } catch (e) {
                this.mealModalError = 'Errore: ' + e.message;
            }
        },

        // ── Debug ────────────────────────────────────────────────────────
        async openDebugModal() {
            this.showDebugModal = true;
            this.debugLoading = true;
            this.debugStatus = null;
            this.debugTrace = [];
            this.debugLlmLog = [];
            this.debugExpandTrace = null;
            this.debugExpandLlm = null;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB?.id || '',
                    start_date: this.startDate,
                });
                const [statusResp, traceResp, logResp] = await Promise.all([
                    fetch('/planner/debug-status?' + params),
                    fetch('/planner/debug-generate?' + params),
                    fetch('/planner/llm-log?last=50'),
                ]);
                if (statusResp.ok) this.debugStatus = await statusResp.json();
                if (traceResp.ok) this.debugTrace = await traceResp.json();
                if (logResp.ok) {
                    const logData = await logResp.json();
                    this.debugLlmLog = logData.calls || [];
                }
            } catch (e) {
                // silenzioso
            } finally {
                this.debugLoading = false;
            }
        },
        closeDebugModal() {
            this.showDebugModal = false;
        },

        // ── Ricetta dettaglio ─────────────────────────────────────────────
        async loadRecipeDetail() {
            const rid = this.mealModalMeal?.items?.[0]?.recipe_id;
            if (!rid) return;
            this.loadingRecipe = true;
            try {
                const r = await fetch(`/recipes/detail/${rid}`);
                this.mealRecipeDetail = r.ok ? await r.json() : null;
                if (!r.ok) this.mealModalError = 'Ricetta non trovata.';
            } catch {
                this.mealRecipeDetail = null;
            } finally {
                this.loadingRecipe = false;
            }
        },

        // ── Utility ──────────────────────────────────────────────────────────
        isPast(dateStr)      { return dateStr < this.today; },
        isFree(meal)         { return meal?.items?.[0]?.food_group === 'free_meal'; },
        isNotEaten(meal)     { return meal?.items?.[0]?.food_group === 'not_eaten'; },
        onStartDateChange() {
            this.weekPlan = null;
            this.error = null;
            this.loadWeekPlan();
        },
        goToToday() {
            const now = new Date();
            const daysToMonday = now.getDay() === 0 ? 6 : now.getDay() - 1;
            const monday = new Date(now);
            monday.setDate(now.getDate() - daysToMonday);
            this.startDate = monday.toISOString().slice(0, 10);
            this.onStartDateChange();
        },
        isToday(dateStr) { return dateStr === this.today; },
        formatDayName(dateStr) {
            return new Date(dateStr + 'T12:00:00').toLocaleDateString('it-IT', { weekday: 'long' });
        },
        formatShortDate(dateStr) {
            return new Date(dateStr + 'T12:00:00').toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
        },
        formatDateLabel(dateStr) {
            if (!dateStr) return '';
            return new Date(dateStr + 'T12:00:00').toLocaleDateString('it-IT', { weekday: 'short', day: 'numeric', month: 'short' });
        },
    },
});

export default WeekView;
