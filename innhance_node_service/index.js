require('dotenv').config();
const express   = require('express');
const cors      = require('cors');
const mongoose  = require('mongoose');
const verifyToken    = require('./middleware/authMiddleware');

// ===== CONNECT TO MONGODB =====
const connectDB = require("./config/database");
connectDB();

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ===== ROUTES =====
app.use('/webhook',       require('./routes/webhook'));


// ===== PROTECTED ROUTE =====
app.get('/api/protected', verifyToken, (req, res) => {
  res.json({ message: 'Protected data accessed', user: req.user });
});

app.get('/', (req, res) => res.send('🏨 Innhance Bot is running!'));


// ===== START SERVER =====
const PORT = process.env.PORT || 5000;
const http = require("http");
const { Server } = require("socket.io");

const server = http.createServer(app);

const io = new Server(server, {
  cors: {
    origin: ["http://localhost:5173","https://innhance-hotels-dashboard.vercel.app"],
    methods: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allowedHeaders: ["Content-Type", "Authorization"],
    credentials: true
  }
});

io.on("connection", (socket) => {

  socket.on("join_hotel_room", (hotelId) => {
    socket.join(hotelId);
    console.log("Joined hotel room:", hotelId);
  });

  socket.on("disconnect", () => {
    console.log("Disconnected:", socket.id);
  });

});

app.set("io", io);

server.listen(PORT, () => {
  console.log("Server running ");
});