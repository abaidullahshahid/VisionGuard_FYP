# VisionGuard - Smart Workplace Safety Management System

## 📋 Project Overview

VisionGuard is a comprehensive React.js web application designed for intelligent workplace safety management with real-time monitoring, incident tracking, and compliance management.

## 🎯 Completed Features

### ✅ Authentication System
- **Login Page** (`/`) - JWT-based authentication with role-based redirects
- Secure token storage in localStorage
- Role-based access control (Admin, Officer, Worker)

---

## 👨‍💼 Admin Dashboard (`/admin`)

### Features:
- **Dashboard Stats** - Overview of users, cameras, incidents, and locations
- **Manage Users** (`/admin/users`) - Add, edit, delete user accounts
- **Manage Locations** (`/admin/locations`) - Configure work locations and zones
- **Manage Cameras** (`/admin/cameras`) - Set up and manage surveillance cameras
- **Configure Safety Rules** (`/admin/rules`) - Define workplace safety policies

### UI/UX:
- Dark sidebar navigation (#1a202c)
- White cards with subtle shadows
- Real-time stats cards with color-coded indicators
- Quick action buttons for navigation
- Smooth transitions and hover effects

---

## 👮 Officer Dashboard (`/officer`)

### Features:
- **Dashboard** - Real-time safety metrics and pending actions
- **View Incidents** (`/officer/incidents`) - Browse and filter safety violations
  - Filter by severity, status, and date
  - Detailed incident information
  - Status tracking
- **Corrective Actions** (`/officer/actions`) - Manage incident resolutions
- **Live Video Feed** (`/officer/live`) - Real-time camera monitoring
  - Camera selection grid
  - Live feed display
  - Active alerts panel
- **Compliance Records** (`/officer/compliance`) - Track workplace compliance
  - Compliance status statistics
  - Location-based compliance tracking
  - Historical records

### Animations & Transitions:
- ✨ Slide-in animations for video feeds
- 🔴 Pulsing live indicators
- ⚠️ Bounce animations for alerts
- 🎨 Smooth card hover effects with elevation
- 📊 Cubic-bezier transitions for professional feel

---

## 👷 Worker Dashboard (`/worker`)

### Features:
- **Dashboard** (`/worker`) - Personal safety metrics
  - Assigned locations count
  - Safety score percentage
  - Tasks completed
  - Active alerts
  - Quick access to key areas
  - Daily safety tips
  - Assignment overview

- **Locations** (`/worker/locations`) - View assigned work areas
  - Search functionality
  - Location details and safety requirements
  - Risk level indicators (High/Medium/Low)
  - Camera counts
  - Last audit information
  - PPE requirements display

- **Safety Instructions** (`/worker/instructions`) - Comprehensive safety guidelines
  - Categorized instructions (PPE, Procedures, Emergency, Hazards)
  - Expandable instruction cards with animations
  - Step-by-step procedures
  - Warnings and important notes
  - Do's and Don'ts sections
  - Required equipment lists
  - Quick reference sidebar
  - Certification status tracking

### Animations & Transitions:
- 📖 Smooth expand/collapse on instruction cards
- 🎯 Staggered list item animations
- 💫 Fade-in effects for expandable content
- 🌊 Wave transitions on category filters

---

## 🎨 Modern UI Features

### Design System:
- **Sidebar**: Dark theme (#1a202c) with white text
- **Cards**: Clean white backgrounds with subtle shadows (0 2px 8px)
- **Buttons**: Multiple styles with smooth hover effects
- **Badges**: Color-coded status indicators
- **Tables**: Responsive with alternating rows

### CSS Animations Included:
- `slideInDown` - Top-down entrance animations
- `slideInUp` - Bottom-up entrance animations
- `slideInLeft` - Left-side entrance animations
- `slideInRight` - Right-side entrance animations
- `scaleIn` - Scale entrance animations
- `pulse` - Pulsing opacity effects
- `bounce` - Bouncing animations
- `blink` - Blinking effects
- `glow` - Shadow glow effects
- `shimmer` - Loading skeleton effects
- `float` - Floating animations
- `rotate` - Rotation animations
- `swing` - Swinging animations

### Hover Effects:
- Cards lift on hover with shadow increase
- Buttons scale slightly on hover (translateY(-2px))
- Links have animated underlines
- Table rows highlight on hover
- Navigation items show left border indicator
- Badges scale on hover

---

## 🔄 API Integration

All pages feature:
- ✅ Bearer token authentication
- ✅ Axios HTTP client for API calls
- ✅ Error handling and user feedback
- ✅ Loading states with animations
- ✅ Success/Error notifications

### API Endpoints Used:
```
GET  /admin/stats
GET  /admin/users
GET  /admin/locations
GET  /admin/cameras
GET  /admin/rules

GET  /officer/stats
GET  /officer/incidents
GET  /officer/actions
GET  /officer/cameras
GET  /officer/alerts
GET  /officer/compliance-records
GET  /officer/compliance-stats

GET  /worker/stats
GET  /worker/assignments
GET  /worker/locations
GET  /worker/safety-instructions
```

---

## 📁 Project Structure

```
frontend/
├── src/
│   ├── Login.jsx                  # Authentication page
│   ├── AdminDashboard.jsx         # Admin main dashboard
│   ├── ManageUsers.jsx            # User management
│   ├── ManageLocations.jsx        # Location management
│   ├── ManageCameras.jsx          # Camera management
│   ├── ConfigureSafetyRules.jsx   # Safety rules configuration
│   ├── OfficerDashboard.jsx       # Officer main dashboard
│   ├── ViewIncidents.jsx          # Incident viewing
│   ├── CorrectiveActions.jsx      # Action management
│   ├── LiveVideoFeed.jsx          # Live video monitoring ✨ NEW
│   ├── ComplianceRecords.jsx      # Compliance tracking ✨ NEW
│   ├── WorkerDashboard.jsx        # Worker main dashboard ✨ NEW
│   ├── WorkerLocations.jsx        # Worker locations ✨ NEW
│   ├── SafetyInstructions.jsx     # Safety guidelines ✨ NEW
│   ├── App.js                     # Main app with routing
│   ├── App.css                    # Global styles & animations
│   └── index.js                   # Entry point
├── public/
├── package.json
└── README.md
```

---

## 🚀 Getting Started

### Installation:
```bash
cd frontend
npm install
npm start
```

### Requirements:
- React.js
- React Router DOM (for navigation)
- Axios (for HTTP requests)
- Backend running on http://localhost:8000

### Environment Variables:
The app uses a fixed backend URL: `http://localhost:8000`

To modify, update the axios calls in each component.

---

## 🎭 User Roles & Access

### Admin
- ✅ Access: `/admin/*`
- ✅ Capabilities: User management, location setup, camera configuration, safety rules
- ✅ Permissions: Create, read, update, delete all resources

### Officer
- ✅ Access: `/officer/*`
- ✅ Capabilities: Incident monitoring, live video feeds, compliance tracking, corrective actions
- ✅ Permissions: View and manage incidents and compliance

### Worker
- ✅ Access: `/worker/*`
- ✅ Capabilities: View assigned locations, access safety instructions
- ✅ Permissions: Read-only access to safety information

---

## 🎬 Animation & Transition Examples

### Card Hover Effect:
```javascript
card: {
  transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
  // On hover: 
  // - Shadow increases
  // - Element lifts (translateY)
  // - Scale slightly increases
}
```

### Navigation Item Hover:
```javascript
navBtn: {
  transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
  // On hover:
  // - Background color changes
  // - Left border indicator animates in
  // - Padding shifts slightly
}
```

### Live Indicators:
```javascript
@keyframes blink {
  0%, 50%, 100% { opacity: 1; }
  25%, 75% { opacity: 0.7; }
}
// Creates pulsing live status badges
```

---

## 📊 Data Flow

### Authentication Flow:
1. User logs in with email/password
2. Backend validates and returns JWT token + role
3. Token stored in localStorage
4. User redirected to role-appropriate dashboard
5. All API requests include `Authorization: Bearer {token}`

### Data Fetching Pattern:
```javascript
useEffect(() => {
  const token = localStorage.getItem("token");
  if (!token) navigate("/");
  
  fetchData();
}, []);

const fetchData = async () => {
  try {
    const res = await axios.get(endpoint, {
      headers: { Authorization: `Bearer ${token}` }
    });
    setData(res.data);
  } catch (err) {
    setError("Failed to fetch data");
  } finally {
    setLoading(false);
  }
};
```

---

## 🎨 Color Palette

- **Primary Blue**: #2b6cb0
- **Success Green**: #22863a
- **Danger Red**: #c53030
- **Warning Orange**: #f59e0b
- **Dark Sidebar**: #1a202c
- **Light Background**: #f7fafc
- **Border Gray**: #e2e8f0
- **Text Dark**: #2d3748
- **Text Light**: #718096

---

## ⚡ Performance Features

- ✅ Lazy loading with loading states
- ✅ Smooth animations with CSS transitions
- ✅ Responsive grid layouts
- ✅ Efficient state management
- ✅ Debounced search/filter operations
- ✅ Cached authentication tokens

---

## 🔐 Security Features

- ✅ JWT token-based authentication
- ✅ Role-based access control
- ✅ Secure token storage
- ✅ Protected routes
- ✅ Bearer token in all API requests
- ✅ Logout clears localStorage

---

## 📝 Notes

- All pages are fully responsive with inline styles
- Animations are GPU-accelerated using transform and opacity
- Loading states prevent user confusion during data fetch
- Error messages provide clear feedback
- Success/error notifications are non-intrusive
- Sidebar is sticky for easy navigation
- Tables support filtering and sorting

---

## 🚀 Future Enhancements

- Real-time WebSocket updates
- Advanced analytics and reporting
- Mobile app version
- Dark mode toggle
- Multi-language support
- Offline functionality
- Export to PDF/Excel
- Advanced search and filtering

---

## 📞 Support

For issues or questions about the VisionGuard system, please contact the development team or check the backend API documentation.

---

**Created**: May 2026  
**Version**: 1.0.0  
**Status**: ✅ Complete with all pages, animations, and modern UI
