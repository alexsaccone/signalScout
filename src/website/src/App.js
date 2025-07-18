import logo from './logo.svg';
import './App.css';
import { useMemo } from 'react';

function PieChart({ a = 0, b = 0 }) {
  const total = a + b;
  const aPercent = total > 0 ? (a / total) * 100 : 0;
  const bPercent = total > 0 ? (b / total) * 100 : 0;

  const background = total === 0 ? 'black' : `conic-gradient(#4CAF50 0% ${aPercent}%, #2196F3 ${aPercent}% ${aPercent + bPercent}%)`;

  return (
    <>
      <div className="pie-chart" style={{ background }}>
        <div className="pie-center">
          {total > 0 ? `$${total}` : '$0'}
        </div>
      </div>
      {total > 0 &&
      <>
        <div className = "result-explain">
          <h3 style = {{color: '#4CAF50'}}> We have made a ${a} profit from the arbitrage bot</h3>
          <h3 style = {{color: '#2196F3'}}> We have made a ${b} profit from the ML bot</h3>
        </div>  
      </>
      } 
    </>
  );
}
function App() {

  return (
    <div className="App">
      <h1> SignalScout Profit Chart </h1>
      <PieChart a={0} b = {0} />
    </div> // The a and b stats need to be pulled from a database obv
  );
}

export default App;
