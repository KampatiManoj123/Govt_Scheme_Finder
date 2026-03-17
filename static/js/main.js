// Government Scheme Hub — Main JS

// Toggle password visibility
function togglePw(inputId, btn) {
  const input = document.getElementById(inputId);
  if (input.type === 'password') {
    input.type = 'text';
    btn.textContent = '🙈';
  } else {
    input.type = 'password';
    btn.textContent = '👁';
  }
}

// Toggle sidebar (mobile)
function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
}

// Toggle user dropdown
function toggleUserMenu() {
  document.getElementById('userDropdown')?.classList.toggle('show');
}

// Close dropdown when clicking outside
document.addEventListener('click', function(e) {
  const dropdown = document.getElementById('userDropdown');
  const userBtn = document.querySelector('.topbar-user');
  if (dropdown && userBtn && !userBtn.contains(e.target)) {
    dropdown.classList.remove('show');
  }
});

// Toggle Save Scheme (Browse / Saved pages)
async function toggleSave(btn) {
  const schemeId = btn.dataset.id;
  const isSaved = btn.classList.contains('saved');
  const action = isSaved ? 'unsave' : 'save';

  try {
    const res = await fetch('/api/save-scheme', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scheme_id: schemeId, action })
    });
    const data = await res.json();
    if (data.success) {
      btn.classList.toggle('saved');
      if (btn.tagName === 'BUTTON') {
        btn.textContent = isSaved ? '☆' : '★';
      }
      showToast(isSaved ? 'Removed from saved' : 'Scheme saved!', isSaved ? 'info' : 'success');
    }
  } catch (err) {
    showToast('Error saving scheme', 'danger');
  }
}

// Toggle Save on Detail Page
async function toggleSaveDetail(btn) {
  const schemeId = btn.dataset.id;
  const isSaved = btn.classList.contains('saved');
  const action = isSaved ? 'unsave' : 'save';

  try {
    const res = await fetch('/api/save-scheme', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scheme_id: schemeId, action })
    });
    const data = await res.json();
    if (data.success) {
      btn.classList.toggle('saved');
      btn.textContent = isSaved ? '☆ Save Scheme' : '★ Saved';
      showToast(isSaved ? 'Removed from saved' : 'Scheme saved!', isSaved ? 'info' : 'success');
    }
  } catch (err) {
    showToast('Error', 'danger');
  }
}

async function sendAIMessage() {

  const input = document.getElementById("ai-input");
  const message = input.value;

  const res = await fetch("/api/ai-chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ message })
  });

  const data = await res.json();

  addMessage("user", message);
  addMessage("ai", data.reply);

  input.value = "";
}

// Toast notifications
function showToast(message, type = 'success') {
  let container = document.querySelector('.flash-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'flash-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `flash flash-${type}`;
  toast.innerHTML = `<span>${message}</span><button onclick="this.parentElement.remove()">×</button>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// Auto-dismiss flash messages
document.querySelectorAll('.flash').forEach(f => {
  setTimeout(() => f.remove(), 4000);
});

// Animate match bars on load
document.addEventListener('DOMContentLoaded', function() {
  // Razorpay Payment
async function startProPayment() {

  try {

    const res = await fetch("/api/create-payment-order", {
      method: "POST"
    });

    const data = await res.json();

    var options = {
      key: razorpay_key, // Razorpay public key
      amount: data.amount,
      currency: "INR",
      name: "Government Scheme Hub",
      description: "Pro Plan",

      order_id: data.order_id,

      // 👇 IMPORTANT PART (User mobile fix)
      prefill: {
        name: user_name,
        email: user_email,
        contact: user_mobile
      },

      theme: {
        color: "#ff7a18"
      },

      handler: function (response) {

        fetch("/api/payment-success", {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify(response)
        })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            window.location.href = "/dashboard";
          }
        });

      }

    };

    var rzp = new Razorpay(options);
    rzp.open();

  } catch (err) {
    alert("Payment failed. Try again.");
  }

}
  // Animate profile progress bars
  document.querySelectorAll('.profile-progress-bar, .nudge-bar, .pcb-fill').forEach(bar => {
    const width = bar.style.width;
    bar.style.width = '0%';
    setTimeout(() => { bar.style.width = width; }, 300);
  });

  // Animate match bars
  document.querySelectorAll('.match-bar-fill').forEach(bar => {
    const width = bar.style.width;
    bar.style.width = '0%';
    setTimeout(() => { bar.style.width = width; }, 500);

  });
});
