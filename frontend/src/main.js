import './styles/index.css';
import { Dashboard } from './pages/Dashboard.js';
import { ChatSpace } from './pages/ChatSpace.js';

const app = document.getElementById('app');
const navDash = document.getElementById('nav-dashboard');
const navChat = document.getElementById('nav-chat');
const navBrand = document.getElementById('nav-brand');

let currentView = null;

function navigate(page) {
  if (currentView) {
    currentView.destroy();
  }
  
  app.innerHTML = '';
  navDash.classList.remove('active');
  navChat.classList.remove('active');

  if (page === 'chat') {
    navChat.classList.add('active');
    currentView = new ChatSpace(app);
  } else {
    navDash.classList.add('active');
    currentView = new Dashboard(app);
  }
}

navDash.addEventListener('click', () => navigate('dashboard'));
navChat.addEventListener('click', () => navigate('chat'));
navBrand.addEventListener('click', (e) => {
  e.preventDefault();
  navigate('dashboard');
});

// Initialize
navigate('dashboard');
