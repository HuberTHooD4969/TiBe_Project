document.addEventListener("DOMContentLoaded", () => {
    // ========== STATE ==========
    let authToken = localStorage.getItem("tibe_token");
    let refreshToken = localStorage.getItem("tibe_refresh_token");
    let currentUser = null;
    let selectedQuality = "1080p";
    let resolutionCosts = {"720p": 1, "1080p": 1, "2K": 2, "4K": 4};
    let currentUnitCost = 1;
    let pollInterval = null;
    let selectedPlan = null;

    // ========== DOM REFS ==========
    const authSection = document.getElementById("auth-section");
    const appSection = document.getElementById("app-section");
    const loginForm = document.getElementById("login-form");
    const registerForm = document.getElementById("register-form");
    const showRegister = document.getElementById("show-register");
    const showLogin = document.getElementById("show-login");
    const loginBtn = document.getElementById("login-btn");
    const registerBtn = document.getElementById("register-btn");
    const logoutBtn = document.getElementById("logout-btn");
    const loginError = document.getElementById("login-error");
    const registerError = document.getElementById("register-error");
    const unitBadge = document.getElementById("unit-badge");
    const openPricingBtn = document.getElementById("open-pricing-btn");
    const pricingModal = document.getElementById("pricing-modal");
    const closePricingBtn = document.getElementById("close-pricing-btn");
    const pricingGrid = document.getElementById("pricing-grid");
    const paymentMethodsSection = document.getElementById("payment-methods-section");
    const payPaystackBtn = document.getElementById("pay-paystack-btn");
    const paymentStatus = document.getElementById("payment-status");

    // Currency state
    let userCurrency = "USD";
    let currencyData = null;
    const adOverlay = document.getElementById("ad-overlay");
    const adCountdown = document.getElementById("ad-countdown");
    const adTimerFill = document.getElementById("ad-timer-fill");
    const adStatus = document.getElementById("ad-status");

    // Main app elements
    const urlInput = document.getElementById("video-url");
    const qualityBtns = document.querySelectorAll(".segment-btn");
    const ultraEnhanceToggle = document.getElementById("ultra-enhance");
    const startBtn = document.getElementById("start-btn");
    const dashboard = document.getElementById("processing-dashboard");
    const statusText = document.getElementById("status-text");
    const progressPercent = document.getElementById("progress-percent");
    const progressBar = document.getElementById("progress-bar");
    const resultDashboard = document.getElementById("result-dashboard");
    const downloadBtn = document.getElementById("download-btn");

    // Mobile guide
    const guideOverlay = document.getElementById("mobile-guide-overlay");
    const closeGuideBtn = document.getElementById("close-guide-btn");
    const guideOkBtn = document.getElementById("guide-ok-btn");
    const tabIos = document.getElementById("tab-ios");
    const tabAndroid = document.getElementById("tab-android");
    const iosContent = document.getElementById("guide-ios-content");
    const androidContent = document.getElementById("guide-android-content");
    let hasShownMobileGuide = false;

    // ========== API HELPERS ==========
    async function apiFetch(url, options = {}) {
        const headers = { "Content-Type": "application/json", ...options.headers };
        if (authToken) {
            headers["Authorization"] = `Bearer ${authToken}`;
        }
        const res = await fetch(url, { ...options, headers });
        if (res.status === 401 && refreshToken) {
            const refreshed = await tryRefresh();
            if (refreshed) {
                headers["Authorization"] = `Bearer ${authToken}`;
                const retryRes = await fetch(url, { ...options, headers });
                return retryRes;
            } else {
                logout();
                return res;
            }
        }
        return res;
    }

    async function tryRefresh() {
        try {
            const res = await fetch("/api/auth/refresh", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ refresh_token: refreshToken })
            });
            if (res.ok) {
                const data = await res.json();
                authToken = data.access_token;
                refreshToken = data.refresh_token;
                localStorage.setItem("tibe_token", authToken);
                localStorage.setItem("tibe_refresh_token", refreshToken);
                return true;
            }
        } catch (e) { /* ignore */ }
        return false;
    }

    // ========== AUTH ==========
    async function login(email, password) {
        loginError.classList.add("hidden");
        loginBtn.disabled = true;
        loginBtn.textContent = "SIGNING IN...";
        try {
            const res = await fetch("/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Login failed");
            authToken = data.access_token;
            refreshToken = data.refresh_token;
            currentUser = data.user;
            localStorage.setItem("tibe_token", authToken);
            localStorage.setItem("tibe_refresh_token", refreshToken);
            showApp();
        } catch (e) {
            loginError.textContent = e.message;
            loginError.classList.remove("hidden");
        } finally {
            loginBtn.disabled = false;
            loginBtn.textContent = "SIGN IN";
        }
    }

    async function register(email, password) {
        registerError.classList.add("hidden");
        registerBtn.disabled = true;
        registerBtn.textContent = "CREATING...";
        try {
            const res = await fetch("/api/auth/register", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Registration failed");
            authToken = data.access_token;
            refreshToken = data.refresh_token;
            currentUser = data.user;
            localStorage.setItem("tibe_token", authToken);
            localStorage.setItem("tibe_refresh_token", refreshToken);
            showApp();
        } catch (e) {
            registerError.textContent = e.message;
            registerError.classList.remove("hidden");
        } finally {
            registerBtn.disabled = false;
            registerBtn.textContent = "CREATE ACCOUNT";
        }
    }

    function logout() {
        authToken = null;
        refreshToken = null;
        currentUser = null;
        localStorage.removeItem("tibe_token");
        localStorage.removeItem("tibe_refresh_token");
        showAuth();
    }

    // ========== CURRENCY DETECTION ==========
    async function detectCurrency() {
        try {
            const res = await fetch("/api/currencies");
            const data = await res.json();
            currencyData = data;
            const locale = navigator.language || "en-US";
            const mapped = data.locale_currency_map[locale];
            if (mapped && data.currencies[mapped]) {
                userCurrency = mapped;
            }
        } catch (e) {
            userCurrency = "USD";
        }
    }

    function formatPrice(usdCents, options = {}) {
        const usdPrice = usdCents / 100;
        if (!currencyData || !currencyData.currencies[userCurrency]) {
            return `$${usdPrice.toFixed(2)}`;
        }
        const cur = currencyData.currencies[userCurrency];
        const localPrice = usdPrice * cur.rate;
        const symbol = cur.symbol;
        const formatted = localPrice.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
        if (options.full) {
            return `${symbol}${formatted} ${cur.code}`;
        }
        // Show both local and USD for transparency
        if (userCurrency !== "USD") {
            return `${symbol}${formatted}`;
        }
        return `${symbol}${formatted}`;
    }

    function formatPerUnit(usdCents, units) {
        const perUnit = usdCents / 100 / units;
        if (!currencyData || !currencyData.currencies[userCurrency]) {
            return `$${perUnit.toFixed(2)}/unit`;
        }
        const cur = currencyData.currencies[userCurrency];
        const local = perUnit * cur.rate;
        return `${cur.symbol}${local.toFixed(2)}/unit`;
    }

    // ========== UI SWITCH ==========
    function showAuth() {
        authSection.classList.remove("hidden");
        appSection.classList.add("hidden");
        pricingModal.classList.add("hidden");
        adOverlay.classList.add("hidden");
    }

    function showApp() {
        authSection.classList.add("hidden");
        appSection.classList.remove("hidden");
        updateUnitBadge();
        updateSubscriptionUI();
    }

    function updateUnitBadge() {
        if (!unitBadge) return;
        apiFetch("/api/user/me").then(r => {
            if (!r.ok) throw new Error();
            return r.json();
        }).then(u => {
            currentUser = u;
            unitBadge.textContent = `${u.units_balance} Units`;
        }).catch(() => {
            if (currentUser) {
                unitBadge.textContent = `${currentUser.units_balance} Units`;
            } else {
                unitBadge.textContent = "0 Units";
            }
        });
    }

    // ========== QUALITY SELECTION ==========
    qualityBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            qualityBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            selectedQuality = btn.dataset.val;
            currentUnitCost = resolutionCosts[selectedQuality] || 1;
        });
    });

    // ========== PROCESSING ENGINE ==========
    function askBuyUnits(quality, needed, balance) {
        const modal = document.getElementById("pricing-modal");
        if (modal) {
            loadPricing();
            paymentMethodsSection.style.display = "none";
            selectedPlan = null;
            modal.classList.remove("hidden");
        }
    }

    startBtn.addEventListener("click", async () => {
        const url = urlInput.value.trim();
        if (!url) {
            alert("Please paste a valid video link first.");
            urlInput.focus();
            return;
        }
        startBtn.disabled = true;
        startBtn.textContent = "CHECKING...";
        dashboard.classList.remove("hidden");
        resultDashboard.classList.add("hidden");
        progressBar.style.width = "0%";
        progressPercent.textContent = "0%";
        statusText.textContent = "Checking account...";
        statusText.style.color = "var(--primary-cyan)";

        try {
            const preRes = await apiFetch("/api/process");
            if (!preRes.ok) throw new Error("Failed to check status");
            const preData = await preRes.json();
            if (preData.resolution_costs) {
                resolutionCosts = preData.resolution_costs;
                currentUnitCost = resolutionCosts[selectedQuality] || 0;
            }

            if (currentUnitCost === 0) {
                // Free resolution (720p / 1080p) — require ad
                await showAdAndProcess(url);
            } else {
                // Paid resolution (2K / 4K) — check units
                if (preData.units_balance >= currentUnitCost) {
                    await processWithUnits(url);
                } else {
                    startBtn.disabled = false;
                    startBtn.textContent = "START ULTRA ENGINE";
                    statusText.textContent = `Need ${currentUnitCost} units for ${selectedQuality}. You have ${preData.units_balance}.`;
                    statusText.style.color = "#ff3366";
                    if (confirm(`You need ${currentUnitCost} units for ${selectedQuality} processing, but you only have ${preData.units_balance} units.\n\nTap OK to buy units or subscribe.`)) {
                        askBuyUnits(selectedQuality, currentUnitCost, preData.units_balance);
                    }
                }
            }
        } catch (e) {
            handleError(e.message);
        }
    });

    async function processWithUnits(url) {
        statusText.textContent = "Starting Engine...";
        startBtn.textContent = "PROCESSING...";
        try {
            const res = await apiFetch("/api/process", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    url: url,
                    quality: selectedQuality,
                    ultra_enhance: ultraEnhanceToggle.checked
                })
            });
            if (!res.ok) {
                const err = await res.json();
                if (res.status === 402) {
                    if (confirm(err.detail + "\n\nTap OK to buy more units.")) {
                        askBuyUnits(selectedQuality, currentUnitCost, 0);
                    }
                    return;
                }
                throw new Error(err.detail || "Failed to start processing.");
            }
            const data = await res.json();
            currentUser.units_balance = data.units_remaining;
            updateUnitBadge();
            pollStatus(data.task_id);
        } catch (e) {
            handleError(e.message);
        }
    }

    async function showAdAndProcess(url) {
        startBtn.textContent = "WATCH AD TO UNLOCK";
        adOverlay.classList.remove("hidden");
        adCountdown.textContent = "30";
        adTimerFill.style.width = "0%";
        adStatus.textContent = "Ad starting...";
        adStatus.style.color = "var(--text-muted)";

        let seconds = 30;
        adStatus.textContent = "Please wait...";
        adStatus.style.color = "var(--primary-cyan)";

        const timer = setInterval(() => {
            seconds--;
            adCountdown.textContent = seconds;
            const pct = ((30 - seconds) / 30) * 100;
            adTimerFill.style.width = `${pct}%`;
            if (seconds <= 0) {
                clearInterval(timer);
                adCountdown.textContent = "0";
                adTimerFill.style.width = "100%";
                adStatus.textContent = "Ad complete! Processing your video...";
                adStatus.style.color = "var(--success-green)";
                setTimeout(async () => {
                    adOverlay.classList.add("hidden");
                    try {
                        const adRes = await apiFetch("/api/ads/complete", { method: "POST" });
                        const adData = await adRes.json();
                        const watchId = adData.ad_watch_id;
                        const res = await apiFetch("/api/process", {
                            method: "POST",
                            headers: { "Content-Type": "application/json", "X-Ad-Watch-Id": watchId },
                            body: JSON.stringify({
                                url: url,
                                quality: selectedQuality,
                                ultra_enhance: ultraEnhanceToggle.checked
                            })
                        });
                        if (!res.ok) {
                            const err = await res.json();
                            throw new Error(err.detail || "Processing failed");
                        }
                        const data = await res.json();
                        pollStatus(data.task_id);
                    } catch (e) {
                        handleError(e.message);
                        adOverlay.classList.add("hidden");
                    }
                }, 500);
            }
        }, 1000);
    }

    function pollStatus(taskId) {
        if (pollInterval) clearInterval(pollInterval);
        startBtn.textContent = "PROCESSING...";
        pollInterval = setInterval(async () => {
            try {
                const res = await apiFetch(`/api/status/${taskId}`);
                if (!res.ok) throw new Error("Status check failed");
                const data = await res.json();
                updateProgressUI(data);
                if (data.status === "completed") {
                    clearInterval(pollInterval);
                    showSuccess(taskId);
                } else if (data.status === "failed") {
                    clearInterval(pollInterval);
                    handleError("Engine Error: " + (data.error || "Unknown error"));
                }
            } catch (e) {
                console.error("Polling error:", e);
            }
        }, 2000);
    }

    function updateProgressUI(data) {
        const progress = data.progress || 0;
        progressBar.style.width = `${progress}%`;
        progressPercent.textContent = `${Math.round(progress)}%`;
        if (data.status === "downloading") {
            statusText.textContent = "Downloading Raw Video...";
            statusText.style.color = "var(--primary-cyan)";
        } else if (data.status === "enhancing") {
            statusText.textContent = "Applying Ultra AI Filters (Multi-Threaded)...";
            statusText.style.color = "var(--accent-purple)";
        } else if (data.status === "merging audio") {
            statusText.textContent = "Merging Original Audio...";
            statusText.style.color = "var(--primary-cyan)";
        }
    }

    function showSuccess(taskId) {
        startBtn.textContent = "START NEW TASK";
        startBtn.disabled = false;
        statusText.textContent = "SUCCESS: VIDEO READY";
        statusText.style.color = "#00ff88";
        progressBar.style.width = "100%";
        progressPercent.textContent = "100%";
        downloadBtn.href = `/api/download/${taskId}`;
        resultDashboard.classList.remove("hidden");
    }

    function handleError(message) {
        startBtn.textContent = "RETRY";
        startBtn.disabled = false;
        statusText.textContent = message;
        statusText.style.color = "#ff3366";
        progressBar.style.background = "#ff3366";
        progressBar.style.boxShadow = "0 0 10px #ff3366";
    }

    // ========== PRICING MODE TOGGLE ==========
    let pricingMode = "onetime"; // "onetime" | "subscription"
    let cachedPricingData = null;

    const toggleBtns = document.querySelectorAll(".toggle-btn");
    if (toggleBtns.length) {
        toggleBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                toggleBtns.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                pricingMode = btn.dataset.mode;
                const plans = pricingMode === "subscription"
                    ? (cachedPricingData?.subscription_plans || [])
                    : (cachedPricingData?.plans || []);
                paymentMethodsSection.style.display = "none";
                selectedPlan = null;
                renderPricing(plans);
            });
        });
    }

    // ========== SUBSCRIPTION UI ==========
    const subBanner = document.getElementById("subscription-banner");
    const subPlanNameDisplay = document.getElementById("sub-plan-name-display");
    const subRenewalDate = document.getElementById("sub-renewal-date");
    const cancelSubBtn = document.getElementById("cancel-sub-btn");

    function updateSubscriptionUI() {
        if (!subBanner) return;
        apiFetch("/api/subscription").then(r => r.json()).then(data => {
            const sub = data.subscription;
            if (sub && sub.status === "active") {
                subBanner.classList.remove("hidden");
                subPlanNameDisplay.textContent = sub.plan_name;
                if (sub.current_period_end) {
                    const d = new Date(sub.current_period_end.replace(" ", "T") + "Z");
                    subRenewalDate.textContent = d.toLocaleDateString(undefined, {
                        year: "numeric", month: "short", day: "numeric"
                    });
                }
            } else {
                subBanner.classList.add("hidden");
            }
        }).catch(() => {
            subBanner.classList.add("hidden");
        });
    }

    if (cancelSubBtn) {
        cancelSubBtn.addEventListener("click", async () => {
            if (!confirm("Cancel your subscription? No further charges will be made. Your remaining units are yours to keep.")) return;
            try {
                const res = await apiFetch("/api/subscription/cancel", { method: "POST" });
                const data = await res.json();
                if (res.ok) {
                    alert(data.message);
                    if (data.manage_url) {
                        window.open(data.manage_url, "_blank");
                    }
                    updateSubscriptionUI();
                    updateUnitBadge();
                } else {
                    alert("Failed to cancel: " + (data.detail || "Unknown error"));
                }
            } catch (e) {
                alert("Failed to cancel subscription");
            }
        });
    }

    // ========== PRICING & PAYMENTS ==========
    async function loadPricing() {
        try {
            const res = await fetch("/api/pricing");
            const data = await res.json();
            cachedPricingData = data;
            // Update resolution costs from server
            if (data.resolution_costs) {
                resolutionCosts = data.resolution_costs;
                currentUnitCost = resolutionCosts[selectedQuality] || 1;
            }
            // Update currency data from response
            if (data.currencies) {
                currencyData = { currencies: data.currencies, locale_currency_map: data.locale_currency_map };
                const locale = navigator.language || "en-US";
                const mapped = data.locale_currency_map[locale];
                if (mapped && data.currencies[mapped]) {
                    userCurrency = mapped;
                }
            }
            // Update pricing intro text
            const introEl = document.querySelector(".pricing-intro");
            if (introEl) {
                if (currentUnitCost === 0) {
                    introEl.innerHTML = `<strong>${selectedQuality}</strong> is <strong>FREE</strong> (ad-supported). Buy units for <strong>2K</strong> (2 units) or <strong>4K</strong> (4 units) processing.`;
                } else {
                    introEl.innerHTML = `Selected: <strong>${selectedQuality}</strong> &mdash; each video costs <strong>${currentUnitCost} unit${currentUnitCost > 1 ? "s" : ""}</strong>. Buy one-time packs or subscribe monthly.`;
                }
            }
            const plans = pricingMode === "subscription" ? (data.subscription_plans || []) : (data.plans || []);
            renderPricing(plans);
        } catch (e) {
            console.error("Failed to load pricing:", e);
        }
    }

    function renderPricing(plans) {
        pricingGrid.innerHTML = "";
        if (!plans || plans.length === 0) {
            pricingGrid.innerHTML = "<p style='text-align:center;color:var(--text-muted);padding:40px;'>No plans available</p>";
            return;
        }
        const cost = currentUnitCost || 1;
        plans.forEach((plan, idx) => {
            const card = document.createElement("div");
            card.className = `pricing-card${plan.popular ? " popular" : ""}`;
            card.dataset.index = idx;
            const localPrice = formatPrice(plan.price_cents, { full: true });
            const localPerUnit = formatPerUnit(plan.price_cents, plan.units);
            const videoCount = Math.floor(plan.units / cost);
            const isSub = pricingMode === "subscription";
            card.innerHTML = `
                <h3>${plan.name}</h3>
                <div class="price">${localPrice}${isSub ? '<span class="price-period">/month</span>' : ""}</div>
                <div class="unit-count">${plan.units} units${isSub ? "/month" : ""}</div>
                <div class="per-unit">${localPerUnit}${isSub ? "/mo" : ""}</div>
                <div class="video-count">≈ ${videoCount} ${selectedQuality} video${videoCount !== 1 ? "s" : ""}</div>
            `;
            card.addEventListener("click", () => {
                document.querySelectorAll(".pricing-card").forEach(c => c.classList.remove("selected"));
                card.classList.add("selected");
                selectedPlan = plan;
                paymentMethodsSection.style.display = "block";
                paymentStatus.textContent = "";
                paymentStatus.className = "auth-error";
            });
            pricingGrid.appendChild(card);
        });
    }

    payPaystackBtn.addEventListener("click", async () => {
        if (!selectedPlan) return;
        paymentStatus.textContent = "Connecting to Paystack...";
        paymentStatus.style.color = "var(--primary-cyan)";
        try {
            let endpoint, body;
            if (pricingMode === "subscription") {
                endpoint = "/api/payment/paystack/subscribe";
                body = { plan_name: selectedPlan.name };
            } else {
                endpoint = "/api/payment/paystack/initialize";
                body = { plan_units: selectedPlan.units, amount_cents: selectedPlan.price_cents };
            }
            const res = await apiFetch(endpoint, { method: "POST", body: JSON.stringify(body) });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Payment failed");
            if (data.authorization_url) {
                window.location.href = data.authorization_url;
            } else {
                throw new Error("No payment URL returned");
            }
        } catch (e) {
            paymentStatus.textContent = "Payment error: " + e.message;
            paymentStatus.style.color = "var(--error-red)";
        }
    });

    // ========== AUTH EVENT LISTENERS ==========
    showRegister.addEventListener("click", (e) => {
        e.preventDefault();
        loginForm.classList.add("hidden");
        registerForm.classList.remove("hidden");
    });
    showLogin.addEventListener("click", (e) => {
        e.preventDefault();
        registerForm.classList.add("hidden");
        loginForm.classList.remove("hidden");
    });
    loginBtn.addEventListener("click", () => {
        const email = document.getElementById("login-email").value.trim();
        const password = document.getElementById("login-password").value;
        if (!email || !password) {
            loginError.textContent = "Please fill in all fields.";
            loginError.classList.remove("hidden");
            return;
        }
        login(email, password);
    });
    registerBtn.addEventListener("click", () => {
        const email = document.getElementById("reg-email").value.trim();
        const password = document.getElementById("reg-password").value;
        if (!email || !password) {
            registerError.textContent = "Please fill in all fields.";
            registerError.classList.remove("hidden");
            return;
        }
        if (password.length < 6) {
            registerError.textContent = "Password must be at least 6 characters.";
            registerError.classList.remove("hidden");
            return;
        }
        register(email, password);
    });
    logoutBtn.addEventListener("click", logout);

    // Enter key support for auth
    document.getElementById("login-password").addEventListener("keydown", (e) => {
        if (e.key === "Enter") loginBtn.click();
    });
    document.getElementById("reg-password").addEventListener("keydown", (e) => {
        if (e.key === "Enter") registerBtn.click();
    });
    document.getElementById("video-url").addEventListener("keydown", (e) => {
        if (e.key === "Enter") startBtn.click();
    });

    // ========== PRICING MODAL ==========
    openPricingBtn.addEventListener("click", () => {
        loadPricing();
        paymentMethodsSection.style.display = "none";
        selectedPlan = null;
        pricingModal.classList.remove("hidden");
    });
    closePricingBtn.addEventListener("click", () => {
        pricingModal.classList.add("hidden");
    });
    pricingModal.addEventListener("click", (e) => {
        if (e.target === pricingModal) pricingModal.classList.add("hidden");
    });

    // ========== MOBILE GUIDE ==========
    function showMobileGuide() {
        if (/android/i.test(navigator.userAgent)) {
            selectAndroidTab();
        } else {
            selectIosTab();
        }
        guideOverlay.classList.remove("hidden");
    }
    function hideMobileGuide() { guideOverlay.classList.add("hidden"); }
    function selectIosTab() {
        tabIos.classList.add("active"); tabAndroid.classList.remove("active");
        iosContent.classList.remove("hidden"); androidContent.classList.add("hidden");
    }
    function selectAndroidTab() {
        tabAndroid.classList.add("active"); tabIos.classList.remove("active");
        androidContent.classList.remove("hidden"); iosContent.classList.add("hidden");
    }
    closeGuideBtn.addEventListener("click", hideMobileGuide);
    tabIos.addEventListener("click", selectIosTab);
    tabAndroid.addEventListener("click", selectAndroidTab);

    guideOkBtn.addEventListener("click", () => {
        hasShownMobileGuide = true;
        hideMobileGuide();
        downloadBtn.click();
        setTimeout(() => { hasShownMobileGuide = false; }, 5000);
    });

    downloadBtn.addEventListener("click", (e) => {
        const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
        if (isMobile && !hasShownMobileGuide) {
            e.preventDefault();
            showMobileGuide();
        }
    });

    // ========== PAYMENT SUCCESS DETECTION ==========
    if (window.location.search.includes("trxref=")) {
        const params = new URLSearchParams(window.location.search);
        const reference = params.get("trxref");
        const token = localStorage.getItem("tibe_token");
        if (reference && token) {
            apiFetch(`/api/payment/paystack/verify?reference=${encodeURIComponent(reference)}`)
                .then(r => r.json())
                .then(data => {
                    if (data.status === "success") {
                        alert(`Payment successful! ${data.units_added} units added to your account.`);
                        apiFetch("/api/user/me")
                            .then(r => r.json())
                            .then(u => {
                                currentUser = u;
                                updateUnitBadge();
                                updateSubscriptionUI();
                            })
                            .catch(() => {});
                    } else {
                        alert("Payment verification failed. Please contact support.");
                    }
                })
                .catch(() => {
                    alert("Payment verification failed. Please contact support.");
                });
        }
        window.history.replaceState({}, "", "/");
    }

    // ========== INIT ==========
    detectCurrency();

    if (authToken && refreshToken) {
        apiFetch("/api/user/me").then(r => {
            if (r.ok) return r.json();
            throw new Error("Not authenticated");
        }).then(u => {
            currentUser = u;
            showApp();
            updateSubscriptionUI();
        }).catch(() => {
            logout();
        });
    }
});
