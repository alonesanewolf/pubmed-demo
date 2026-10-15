import { Route, Routes } from 'react-router-dom';
import AnalysisPage from './pages/AnalysisPage';
import AboutPage from './pages/AboutPage';
import Layout from './components/Layout';

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<AnalysisPage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="*" element={<AnalysisPage />} />
      </Routes>
    </Layout>
  );
}
