const express = require('express');
const cors = require('cors');
require('dotenv').config();

// 🔥 DEBUG ENV VARIABLES
console.log("JWT_SECRET loaded:", process.env.JWT_SECRET);
console.log("GEMINI key exists:", !!process.env.GEMINI_API_KEY);
console.log("APOLLO key exists:", !!process.env.APOLLO_API_KEY);

const authRoutes = require('./routes/auth');
const emailRoutes = require('./routes/email');
const apolloRoutes = require('./routes/apollo');
const resumeRoutes = require('./routes/resume');
const chatRoutes = require('./routes/chat');
const trackingRoutes = require('./routes/tracking');

const app = express();

app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Routes
app.use('/api/auth', authRoutes);
app.use('/api/email', emailRoutes);
app.use('/api/apollo', apolloRoutes);
app.use('/api/resume', resumeRoutes);
app.use('/api/chat', chatRoutes);
app.use('/api/tracking', trackingRoutes);

// Health check
app.get('/', (req, res) => {
  res.json({ status: 'Outreach AI Backend Running' });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});