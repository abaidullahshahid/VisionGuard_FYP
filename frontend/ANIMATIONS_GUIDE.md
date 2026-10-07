# VisionGuard - CSS Animations & Transitions Guide

## 🎬 Available Animations in App.css

All animations are defined in `App.css` and can be used in any component.

### 1. **Entrance Animations**

#### slideInDown
```css
@keyframes slideInDown {
  from { opacity: 0; transform: translateY(-20px); }
  to { opacity: 1; transform: translateY(0); }
}
```
**Usage**: Top-down entrance effects for modals, headers, video feeds
```javascript
style={{ animation: "slideInDown 0.5s ease" }}
```

#### slideInUp
```css
@keyframes slideInUp {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}
```
**Usage**: Bottom-up entrance for cards, buttons, content reveal
```javascript
style={{ animation: "slideInUp 0.5s ease" }}
```

#### slideInLeft
```css
@keyframes slideInLeft {
  from { opacity: 0; transform: translateX(-20px); }
  to { opacity: 1; transform: translateX(0); }
}
```
**Usage**: Left-side entrance for sidebars, panels
```javascript
style={{ animation: "slideInLeft 0.4s ease" }}
```

#### slideInRight
```css
@keyframes slideInRight {
  from { opacity: 0; transform: translateX(20px); }
  to { opacity: 1; transform: translateX(0); }
}
```
**Usage**: Right-side entrance for notifications, drawers
```javascript
style={{ animation: "slideInRight 0.4s ease" }}
```

#### scaleIn
```css
@keyframes scaleIn {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}
```
**Usage**: Grid items, card elements, focused content
```javascript
style={{ animation: "scaleIn 0.4s ease" }}
```

---

### 2. **Continuous/Loop Animations**

#### pulse
```css
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
```
**Usage**: Camera icons, loading indicators, live status
```javascript
style={{ animation: "pulse 2s infinite" }}
```

#### bounce
```css
@keyframes bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}
```
**Usage**: Alert icons, notification badges, attention seekers
```javascript
style={{ animation: "bounce 1s infinite" }}
```

#### float
```css
@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}
```
**Usage**: Decorative elements, emphasis icons
```javascript
style={{ animation: "float 3s infinite" }}
```

#### rotate
```css
@keyframes rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
```
**Usage**: Loading spinners, refresh indicators
```javascript
style={{ animation: "rotate 2s linear infinite" }}
```

#### swing
```css
@keyframes swing {
  0% { transform: rotate(-5deg); }
  50% { transform: rotate(5deg); }
  100% { transform: rotate(-5deg); }
}
```
**Usage**: Attention-getting effects, subtle hover states
```javascript
style={{ animation: "swing 0.6s infinite" }}
```

#### blink
```css
@keyframes blink {
  0%, 50%, 100% { opacity: 1; }
  25%, 75% { opacity: 0.7; }
}
```
**Usage**: Live indicators, status badges
```javascript
style={{ animation: "blink 1.5s infinite" }}
```

#### glow
```css
@keyframes glow {
  0%, 100% { box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06); }
  50% { box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12); }
}
```
**Usage**: Important elements, active states
```javascript
style={{ animation: "glow 2s ease-in-out infinite" }}
```

---

### 3. **Loading & Special Effects**

#### shimmer
```css
@keyframes shimmer {
  0% { background-position: -1000px 0; }
  100% { background-position: 1000px 0; }
}
```
**Usage**: Skeleton loaders, loading placeholders
```javascript
style={{
  background: "linear-gradient(90deg, #e2e8f0 25%, #f7fafc 50%, #e2e8f0 75%)",
  backgroundSize: "1000px 100%",
  animation: "shimmer 2s infinite"
}}
```

#### gradientShift
```css
@keyframes gradientShift {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
```
**Usage**: Gradient backgrounds, animated themes
```javascript
style={{
  background: "linear-gradient(-45deg, #ee7752, #e73c7e, #23a6d5, #23d5ab)",
  backgroundSize: "400% 400%",
  animation: "gradientShift 15s ease infinite"
}}
```

#### fadeInPage
```css
@keyframes fadeInPage {
  from { opacity: 0; }
  to { opacity: 1; }
}
```
**Usage**: Page transitions, initial load
```javascript
style={{ animation: "fadeInPage 0.3s ease" }}
```

---

## 🎯 Practical Examples

### Example 1: Animated Card
```javascript
<div style={{
  backgroundColor: "#fff",
  borderRadius: "12px",
  padding: "24px",
  boxShadow: "0 2px 8px rgba(0,0,0,0.06)",
  animation: "slideInUp 0.5s ease-out",
  transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
  cursor: "pointer"
}}>
  Card content
</div>
```

### Example 2: Live Status Badge
```javascript
<div style={{
  display: "inline-block",
  padding: "6px 12px",
  backgroundColor: "#c53030",
  color: "#fff",
  borderRadius: "20px",
  fontSize: "12px",
  fontWeight: "700",
  animation: "blink 1.5s infinite"
}}>
  🔴 LIVE
</div>
```

### Example 3: Loading Spinner
```javascript
<div style={{
  width: "40px",
  height: "40px",
  border: "4px solid #e2e8f0",
  borderTopColor: "#2b6cb0",
  borderRadius: "50%",
  animation: "rotate 1s linear infinite"
}}/>
```

### Example 4: Alert Item with Bounce
```javascript
<div style={{
  display: "flex",
  alignItems: "center",
  gap: "12px",
  padding: "12px",
  backgroundColor: "#fff"
}}>
  <span style={{ fontSize: "24px", animation: "bounce 1s infinite" }}>⚠️</span>
  <span>Important Alert</span>
</div>
```

### Example 5: Expandable Card with Smooth Transition
```javascript
<div style={{
  backgroundColor: "#fff",
  borderRadius: "12px",
  overflow: "hidden",
  transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
  maxHeight: isExpanded ? "500px" : "100px"
}}>
  Content
</div>
```

---

## 🎨 Transition Timing Functions

**Use these for smooth, professional animations:**

- `ease` - Slow start and end, faster in middle
- `ease-out` - Faster start, slower end
- `ease-in` - Slower start, faster end
- `ease-in-out` - Slow start and end, faster middle
- `cubic-bezier(0.4, 0, 0.2, 1)` - Professional material design feel
- `linear` - Constant speed (use for rotations)

---

## 🚀 Performance Tips

1. **Use transform & opacity** instead of width/height for animations
   ```javascript
   // ✅ Good - GPU accelerated
   style={{ transform: "translateY(-4px)", opacity: 0.9 }}
   
   // ❌ Bad - Causes reflow
   style={{ top: "-4px", opacity: 0.9 }}
   ```

2. **Limit animation duration** to 200-600ms for UI elements
   ```javascript
   animation: "slideInUp 0.5s ease" // Good
   animation: "slideInUp 3s ease"   // Too slow
   ```

3. **Use will-change sparingly** for complex animations
   ```javascript
   style={{ willChange: "transform", animation: "..." }}
   ```

4. **Stagger animations** for visual interest without performance hit
   ```javascript
   {items.map((item, idx) => (
     <div style={{ animation: `slideInUp 0.5s ease ${idx * 0.1}s` }}>
       {item}
     </div>
   ))}
   ```

---

## 🎭 Hover Effects Pattern

All interactive elements in VisionGuard follow this pattern:

```javascript
element: {
  // Normal state
  backgroundColor: "#fff",
  borderRadius: "12px",
  boxShadow: "0 2px 8px rgba(0,0,0,0.06)",
  
  // Smooth transition for all properties
  transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
  
  // On hover (handled by browser)
  // transform: translateY(-4px)
  // boxShadow: 0 8px 16px rgba(0,0,0,0.12)
}
```

---

## 📱 Responsive Animation Adjustments

```javascript
@media (max-width: 768px) {
  .grid-item {
    /* Reduce animation delays on mobile */
    animation-delay: 0s !important;
  }
  
  button {
    /* Disable hover animations on touch devices */
    animation: none;
  }
}
```

---

## ✨ Animation Combinations

### Entrance + Bounce
```javascript
style={{
  animation: "slideInUp 0.5s ease, bounce 0.5s ease 0.5s"
}}
```

### Scale + Glow
```javascript
style={{
  animation: "scaleIn 0.4s ease, glow 2s ease-in-out infinite"
}}
```

### Fade + Float
```javascript
style={{
  animation: "fadeInPage 0.3s ease, float 3s ease-in-out infinite"
}}
```

---

## 📚 CSS Class Usage

For global reusable styles, use these classes from App.css:

```javascript
// Entrance animations
className="card"           // slideInUp + hover effect
className="text-animate"   // slideInUp
className="heading"        // slideInDown

// Icon animations
className="icon-spin"      // rotate
className="icon-pulse"     // pulse
className="icon-bounce"    // bounce
className="icon-float"     // float

// Interactive
className="link-hover"     // Underline animation
className="card-hover"     // Lift on hover
```

---

## 🎬 Summary Table

| Animation | Duration | Use Case | Loop |
|-----------|----------|----------|------|
| slideInDown | 0.4-0.5s | Headers, modals | No |
| slideInUp | 0.4-0.5s | Cards, content | No |
| slideInLeft | 0.4s | Sidebars | No |
| slideInRight | 0.4s | Notifications | No |
| scaleIn | 0.4s | Grid items | No |
| pulse | 2s | Loading, icons | Yes |
| bounce | 1s | Alerts, badges | Yes |
| float | 3s | Decorative | Yes |
| rotate | 1-2s | Spinners | Yes |
| swing | 0.6s | Attention | Yes |
| blink | 1.5s | Live status | Yes |
| glow | 2s | Emphasis | Yes |
| shimmer | 2s | Skeleton | Yes |
| fadeInPage | 0.3s | Page load | No |

---

**All animations are production-ready and optimized for performance!**
