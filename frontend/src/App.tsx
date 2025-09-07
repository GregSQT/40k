import './App.css'

function App() {
  return (
    <div style={{ 
      minHeight: '100vh', 
      backgroundColor: '#111827', 
      color: 'white', 
      padding: '2rem',
      fontFamily: 'system-ui, sans-serif'
    }}>
      <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
        <header style={{ marginBottom: '2rem' }}>
          <h1 style={{ fontSize: '3rem', fontWeight: 'bold', marginBottom: '0.5rem' }}>
            Warhammer 40K Engine
          </h1>
          <p style={{ color: '#9CA3AF' }}>AI_TURN.md Compliant Implementation</p>
        </header>
        
        <div style={{ 
          display: 'grid', 
          gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', 
          gap: '1.5rem' 
        }}>
          <div style={{ backgroundColor: '#1F2937', padding: '1.5rem', borderRadius: '0.5rem' }}>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 'bold', marginBottom: '1rem' }}>
              Engine Status
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Architecture:</span>
                <span style={{ color: '#10B981' }}>AI_TURN.md Compliant</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>State Management:</span>
                <span style={{ color: '#10B981' }}>Single Source</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Step Counting:</span>
                <span style={{ color: '#10B981' }}>Built-in</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Activation:</span>
                <span style={{ color: '#10B981' }}>Sequential</span>
              </div>
            </div>
          </div>
          
          <div style={{ backgroundColor: '#1F2937', padding: '1.5rem', borderRadius: '0.5rem' }}>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 'bold', marginBottom: '1rem' }}>
              Implementation Progress
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Engine Core:</span>
                <span style={{ color: '#F59E0B' }}>Ready to Implement</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Movement Phase:</span>
                <span style={{ color: '#F59E0B' }}>Phase 0</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Combat Phase:</span>
                <span style={{ color: '#F59E0B' }}>Phase 0</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Frontend Integration:</span>
                <span style={{ color: '#10B981' }}>Operational</span>
              </div>
            </div>
          </div>
        </div>
        
        <div style={{ 
          marginTop: '2rem', 
          backgroundColor: '#1F2937', 
          padding: '1.5rem', 
          borderRadius: '0.5rem' 
        }}>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 'bold', marginBottom: '1rem' }}>
            Phase 0: Architecture Validation
          </h2>
          <p style={{ color: '#9CA3AF', marginBottom: '1rem' }}>
            Environment configured successfully. Ready to begin AI_TURN.md compliant W40K engine implementation.
          </p>
          <div style={{ fontSize: '0.875rem', color: '#6B7280' }}>
            Next: Implement movement phase handlers with built-in step counting and sequential activation.
          </div>
        </div>
      </div>
    </div>
  )
}

export default App
