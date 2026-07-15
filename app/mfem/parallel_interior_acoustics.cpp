// MPI-distributed backend for the reduced HornCAD interior/aperture formulation.
#include <mfem.hpp>
#include <mfem/linalg/superlu.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <complex>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <string>
#include <vector>

using namespace mfem;

namespace
{
constexpr double pi = 3.14159265358979323846;

struct TraceEntry
{
   HYPRE_BigInt pressure_dof;
   double x, y, z, weight;
};

struct BoundaryTrace
{
   std::vector<TraceEntry> entries;
};

int vertex_dof(FiniteElementSpace &fes, int vertex)
{
   Array<int> dofs;
   fes.GetVertexDofs(vertex, dofs);
   MFEM_VERIFY(dofs.Size() == 1, "P1 H1 vertex must have one scalar DOF");
   return dofs[0] < 0 ? -1 - dofs[0] : dofs[0];
}

double triangle_area(const double *a, const double *b, const double *c)
{
   const double ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2];
   const double vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
   const double cx = uy * vz - uz * vy;
   const double cy = uz * vx - ux * vz;
   const double cz = ux * vy - uy * vx;
   return 0.5 * std::sqrt(cx * cx + cy * cy + cz * cz);
}

BoundaryTrace boundary_trace(ParMesh &mesh, ParFiniteElementSpace &fes,
                             int attribute, MPI_Comm comm)
{
   std::vector<TraceEntry> local;
   Array<int> vertices;
   for (int element = 0; element < mesh.GetNBE(); ++element)
   {
      if (mesh.GetBdrAttribute(element) != attribute) { continue; }
      mesh.GetBdrElementVertices(element, vertices);
      MFEM_VERIFY(vertices.Size() == 3, "trace boundaries must be triangular");
      const double *a = mesh.GetVertex(vertices[0]);
      const double *b = mesh.GetVertex(vertices[1]);
      const double *c = mesh.GetVertex(vertices[2]);
      const double share = triangle_area(a, b, c) / 3.0;
      for (int corner = 0; corner < 3; ++corner)
      {
         const int ldof = vertex_dof(fes, vertices[corner]);
         const double *point = mesh.GetVertex(vertices[corner]);
         local.push_back({fes.GetGlobalTDofNumber(ldof), point[0], point[1],
                          point[2], share});
      }
   }

   int ranks = 1;
   MPI_Comm_size(comm, &ranks);
   const int local_bytes = static_cast<int>(local.size() * sizeof(TraceEntry));
   std::vector<int> counts(ranks), offsets(ranks);
   MPI_Allgather(&local_bytes, 1, MPI_INT, counts.data(), 1, MPI_INT, comm);
   int total_bytes = 0;
   for (int rank = 0; rank < ranks; ++rank)
   {
      offsets[rank] = total_bytes;
      total_bytes += counts[rank];
   }
   std::vector<unsigned char> gathered(total_bytes);
   MPI_Allgatherv(local.data(), local_bytes, MPI_BYTE, gathered.data(),
                  counts.data(), offsets.data(), MPI_BYTE, comm);

   std::map<HYPRE_BigInt, TraceEntry> combined;
   const int count = total_bytes / static_cast<int>(sizeof(TraceEntry));
   const auto *raw = reinterpret_cast<const TraceEntry *>(gathered.data());
   for (int i = 0; i < count; ++i)
   {
      auto found = combined.find(raw[i].pressure_dof);
      if (found == combined.end()) { combined[raw[i].pressure_dof] = raw[i]; }
      else { found->second.weight += raw[i].weight; }
   }
   BoundaryTrace trace;
   for (const auto &[dof, entry] : combined) { trace.entries.push_back(entry); }
   MFEM_VERIFY(!trace.entries.empty(), "requested boundary attribute is empty");
   return trace;
}

class DistributedLayout
{
public:
   MPI_Comm comm;
   int rank, ranks, pressure_local, mouth_size, block_size, vector_size;
   HYPRE_BigInt pressure_begin, pressure_end;

   DistributedLayout(MPI_Comm comm_, const ParFiniteElementSpace &fes,
                     int mouth_size_)
      : comm(comm_), mouth_size(mouth_size_)
   {
      MPI_Comm_rank(comm, &rank);
      MPI_Comm_size(comm, &ranks);
      pressure_begin = fes.GetMyTDofOffset();
      pressure_local = fes.GetTrueVSize();
      pressure_end = pressure_begin + pressure_local;
      block_size = pressure_local + mouth_size;
      vector_size = 2 * block_size;
   }

   bool owns(HYPRE_BigInt dof) const
   { return dof >= pressure_begin && dof < pressure_end; }

   int local_pressure(HYPRE_BigInt dof) const
   { return static_cast<int>(dof - pressure_begin); }

   double dot(const Vector &a, const Vector &b) const
   {
      double local = 0.0;
      for (int part = 0; part < 2; ++part)
      {
         const int base = part * block_size;
         for (int i = 0; i < pressure_local; ++i)
         { local += a[base + i] * b[base + i]; }
         if (rank == 0)
         {
            for (int i = 0; i < mouth_size; ++i)
            {
               local += a[base + pressure_local + i] *
                        b[base + pressure_local + i];
            }
         }
      }
      double global = 0.0;
      MPI_Allreduce(&local, &global, 1, MPI_DOUBLE, MPI_SUM, comm);
      return global;
   }

   double norm(const Vector &a) const { return std::sqrt(dot(a, a)); }

   void gather_trace(const Vector &pressure, const BoundaryTrace &trace,
                     Vector &values) const
   {
      values.SetSize(static_cast<int>(trace.entries.size()));
      values = 0.0;
      for (int i = 0; i < values.Size(); ++i)
      {
         const auto dof = trace.entries[i].pressure_dof;
         if (owns(dof)) { values[i] = pressure[local_pressure(dof)]; }
      }
      MPI_Allreduce(MPI_IN_PLACE, values.GetData(), values.Size(), MPI_DOUBLE,
                    MPI_SUM, comm);
   }
};

class DistributedMixedOperator
{
   const DistributedLayout &layout_;
   const HypreParMatrix &pressure_;
   const BoundaryTrace &mouth_;
   const DenseMatrix &zr_, &zi_;
   double coupling_;

public:
   DistributedMixedOperator(const DistributedLayout &layout,
                            const HypreParMatrix &pressure,
                            const BoundaryTrace &mouth,
                            const DenseMatrix &zr, const DenseMatrix &zi,
                            double coupling)
      : layout_(layout), pressure_(pressure), mouth_(mouth), zr_(zr), zi_(zi),
        coupling_(coupling) { }

   void Mult(const Vector &x, Vector &y) const
   {
      const int n = layout_.pressure_local, m = layout_.mouth_size;
      const int block = layout_.block_size;
      y.SetSize(layout_.vector_size);
      y = 0.0;
      Vector pr(const_cast<double *>(x.GetData()), n);
      Vector vr(const_cast<double *>(x.GetData()) + n, m);
      Vector pi(const_cast<double *>(x.GetData()) + block, n);
      Vector vi(const_cast<double *>(x.GetData()) + block + n, m);
      Vector ypr(y.GetData(), n), yvr(y.GetData() + n, m);
      Vector ypi(y.GetData() + block, n), yvi(y.GetData() + block + n, m);
      pressure_.Mult(pr, ypr);
      pressure_.Mult(pi, ypi);
      zr_.Mult(vr, yvr);
      zi_.AddMult(vi, yvr, -1.0);
      zi_.Mult(vr, yvi);
      zr_.AddMult(vi, yvi);
      Vector trace_r, trace_i;
      layout_.gather_trace(pr, mouth_, trace_r);
      layout_.gather_trace(pi, mouth_, trace_i);
      for (int i = 0; i < m; ++i)
      {
         yvr[i] -= trace_r[i];
         yvi[i] -= trace_i[i];
         const auto &entry = mouth_.entries[i];
         if (layout_.owns(entry.pressure_dof))
         {
            const int local = layout_.local_pressure(entry.pressure_dof);
            ypr[local] -= coupling_ * entry.weight * vi[i];
            ypi[local] += coupling_ * entry.weight * vr[i];
         }
      }
   }
};

class DistributedPreconditioner
{
   const DistributedLayout &layout_;
   const BoundaryTrace &mouth_;
   std::unique_ptr<SuperLURowLocMatrix> pressure_matrix_;
   std::unique_ptr<SuperLUSolver> pressure_solver_;
   DenseMatrix zr_, zi_;
   Array<int> pivots_;
   ComplexLUFactors aperture_solver_;

public:
   DistributedPreconditioner(const DistributedLayout &layout,
                             const HypreParMatrix &pressure,
                             const BoundaryTrace &mouth,
                             const DenseMatrix &zr, const DenseMatrix &zi,
                             int)
      : layout_(layout), mouth_(mouth), zr_(zr), zi_(zi), pivots_(zr.Height())
   {
      pressure_matrix_ = std::make_unique<SuperLURowLocMatrix>(pressure);
      pressure_solver_ = std::make_unique<SuperLUSolver>(*pressure_matrix_);
      pressure_solver_->SetPrintStatistics(false);
      pressure_solver_->SetColumnPermutation(superlu::MMD_AT_PLUS_A);
      aperture_solver_.data_r = zr_.Data();
      aperture_solver_.data_i = zi_.Data();
      aperture_solver_.ipiv = pivots_.GetData();
      MFEM_VERIFY(aperture_solver_.Factor(zr_.Height()),
                  "aperture impedance factorization failed");
   }

   void Mult(const Vector &x, Vector &y) const
   {
      const int n = layout_.pressure_local, m = layout_.mouth_size;
      const int block = layout_.block_size;
      y.SetSize(layout_.vector_size);
      y = 0.0;
      Vector xr(const_cast<double *>(x.GetData()), n), yr(y.GetData(), n);
      Vector xi(const_cast<double *>(x.GetData()) + block, n);
      Vector yi(y.GetData() + block, n);
      Array<const Vector *> pressure_rhs({&xr, &xi});
      Array<Vector *> pressure_solution({&yr, &yi});
      pressure_solver_->ArrayMult(pressure_rhs, pressure_solution);
      Vector trace_r, trace_i;
      layout_.gather_trace(yr, mouth_, trace_r);
      layout_.gather_trace(yi, mouth_, trace_i);
      Vector aperture_r(y.GetData() + n, m);
      Vector aperture_i(y.GetData() + block + n, m);
      for (int i = 0; i < m; ++i)
      {
         aperture_r[i] = x[n + i] + trace_r[i];
         aperture_i[i] = x[block + n + i] + trace_i[i];
      }
      aperture_solver_.Solve(m, 1, aperture_r.GetData(), aperture_i.GetData());
   }
};

struct KrylovResult
{
   bool converged = false;
   int iterations = 0;
   double relative_residual = 0.0;
};

KrylovResult fgmres(const DistributedLayout &layout,
                    const DistributedMixedOperator &op,
                    const DistributedPreconditioner &preconditioner,
                    const Vector &b, Vector &x, int maximum_iterations,
                    int restart, double tolerance)
{
   const double bnorm = layout.norm(b);
   Vector ax(layout.vector_size), residual(layout.vector_size);
   op.Mult(x, ax);
   subtract(b, ax, residual);
   double beta = layout.norm(residual);
   KrylovResult result;
   result.relative_residual = beta / bnorm;
   while (result.iterations < maximum_iterations &&
          result.relative_residual > tolerance)
   {
      const int cycle = std::min(restart, maximum_iterations - result.iterations);
      std::vector<Vector> v(cycle + 1), z(cycle);
      std::vector<std::vector<double>> h(cycle + 1,
                                         std::vector<double>(cycle, 0.0));
      std::vector<double> cs(cycle), sn(cycle), g(cycle + 1, 0.0);
      v[0].SetSize(layout.vector_size);
      v[0] = residual;
      v[0] /= beta;
      g[0] = beta;
      int used = 0;
      for (int j = 0; j < cycle; ++j)
      {
         z[j].SetSize(layout.vector_size);
         preconditioner.Mult(v[j], z[j]);
         Vector w(layout.vector_size);
         op.Mult(z[j], w);
         for (int i = 0; i <= j; ++i)
         {
            h[i][j] = layout.dot(w, v[i]);
            w.Add(-h[i][j], v[i]);
         }
         h[j + 1][j] = layout.norm(w);
         v[j + 1].SetSize(layout.vector_size);
         if (h[j + 1][j] > 0.0)
         {
            v[j + 1] = w;
            v[j + 1] /= h[j + 1][j];
         }
         else { v[j + 1] = 0.0; }
         for (int i = 0; i < j; ++i)
         {
            const double a = h[i][j], q = h[i + 1][j];
            h[i][j] = cs[i] * a + sn[i] * q;
            h[i + 1][j] = -sn[i] * a + cs[i] * q;
         }
         const double denominator = std::hypot(h[j][j], h[j + 1][j]);
         cs[j] = denominator == 0.0 ? 1.0 : h[j][j] / denominator;
         sn[j] = denominator == 0.0 ? 0.0 : h[j + 1][j] / denominator;
         h[j][j] = cs[j] * h[j][j] + sn[j] * h[j + 1][j];
         h[j + 1][j] = 0.0;
         g[j + 1] = -sn[j] * g[j];
         g[j] = cs[j] * g[j];
         ++result.iterations;
         used = j + 1;
         if (std::abs(g[j + 1]) / bnorm <= tolerance) { break; }
      }
      std::vector<double> coefficients(used);
      for (int i = used - 1; i >= 0; --i)
      {
         double value = g[i];
         for (int j = i + 1; j < used; ++j)
         { value -= h[i][j] * coefficients[j]; }
         coefficients[i] = value / h[i][i];
      }
      for (int i = 0; i < used; ++i) { x.Add(coefficients[i], z[i]); }
      op.Mult(x, ax);
      subtract(b, ax, residual);
      beta = layout.norm(residual);
      result.relative_residual = beta / bnorm;
      if (layout.rank == 0)
      {
         std::cout << "fgmres iterations=" << result.iterations
                   << " relative_residual=" << result.relative_residual
                   << std::endl;
      }
   }
   result.converged = result.relative_residual <= tolerance;
   return result;
}
} // namespace

int main(int argc, char *argv[])
{
   Mpi::Init(argc, argv);
   MPI_Comm comm = MPI_COMM_WORLD;
   int rank = 0, ranks = 1;
   MPI_Comm_rank(comm, &rank);
   MPI_Comm_size(comm, &ranks);
   if (argc < 3)
   {
      if (rank == 0)
      {
         std::cerr << "usage: horncad_mfem_interior_parallel MESH.msh "
                      "FREQUENCY_HZ [--quadrant-symmetry] "
                      "[--output-prefix PATH]\n";
      }
      return 2;
   }
   const std::string mesh_path = argv[1];
   const double frequency = std::stod(argv[2]);
   std::string output_prefix;
   bool quadrant_symmetry = false;
   for (int argument = 3; argument < argc; ++argument)
   {
      const std::string option = argv[argument];
      if (option == "--quadrant-symmetry") { quadrant_symmetry = true; }
      else if (option == "--output-prefix" && argument + 1 < argc)
      { output_prefix = argv[++argument]; }
      else
      {
         if (rank == 0) { std::cerr << "invalid output arguments\n"; }
         return 2;
      }
   }
   MFEM_VERIFY(frequency > 0.0, "invalid solver parameters");
   constexpr double density = 1.2041;
   constexpr double sound_speed = 343.21;
   constexpr double volume_velocity = 1.0;
   const double omega = 2.0 * pi * frequency;
   const double wave_number = omega / sound_speed;

   Mesh serial_mesh(mesh_path.c_str(), 1, 1);
   ParMesh mesh(comm, serial_mesh);
   serial_mesh.Clear();
   H1_FECollection collection(1, mesh.Dimension());
   ParFiniteElementSpace space(&mesh, &collection);
   ConstantCoefficient negative_k_squared(-wave_number * wave_number);
   ParBilinearForm helmholtz(&space);
   helmholtz.AddDomainIntegrator(new DiffusionIntegrator);
   helmholtz.AddDomainIntegrator(new MassIntegrator(negative_k_squared));
   helmholtz.Assemble();
   helmholtz.Finalize();
   std::unique_ptr<HypreParMatrix> pressure(helmholtz.ParallelAssemble());
   const BoundaryTrace throat = boundary_trace(mesh, space, 2, comm);
   const BoundaryTrace mouth = boundary_trace(mesh, space, 3, comm);
   DistributedLayout layout(comm, space, static_cast<int>(mouth.entries.size()));
   const int mouth_size = layout.mouth_size;
   if (rank == 0)
   {
      std::cout << "pressure_dofs=" << space.GlobalTrueVSize()
                << " pressure_local_rank0=" << layout.pressure_local
                << " mouth_dofs=" << mouth_size
                << " throat_dofs=" << throat.entries.size() << std::endl;
   }
   DenseMatrix radiation_real(mouth_size), radiation_imag(mouth_size);
   for (int row = 0; row < mouth_size; ++row)
   {
      for (int column = 0; column < mouth_size; ++column)
      {
         std::complex<double> integral = 0.0;
         const int image_count = quadrant_symmetry ? 4 : 1;
         for (int image = 0; image < image_count; ++image)
         {
            const double image_x = (image & 1) ? -mouth.entries[column].x
                                                : mouth.entries[column].x;
            const double image_y = (image & 2) ? -mouth.entries[column].y
                                                : mouth.entries[column].y;
            const double dx = mouth.entries[row].x - image_x;
            const double dy = mouth.entries[row].y - image_y;
            const double dz = mouth.entries[row].z - mouth.entries[column].z;
            const double distance = std::sqrt(dx * dx + dy * dy + dz * dz);
            if (distance < 1e-14)
            {
               const double radius = std::sqrt(mouth.entries[column].weight / pi);
               integral += 2.0 * pi *
                  (1.0 - std::exp(std::complex<double>(0.0, -wave_number * radius))) /
                  std::complex<double>(0.0, wave_number);
            }
            else
            {
               integral += mouth.entries[column].weight *
                  std::exp(std::complex<double>(0.0, -wave_number * distance)) /
                  distance;
            }
         }
         const std::complex<double> impedance =
            std::complex<double>(0.0, density * omega / (2.0 * pi)) * integral;
         radiation_real(row, column) = impedance.real();
         radiation_imag(row, column) = impedance.imag();
      }
   }

   DistributedMixedOperator system(layout, *pressure, mouth, radiation_real,
                                   radiation_imag, omega * density);
   DistributedPreconditioner preconditioner(layout, *pressure, mouth,
                                             radiation_real, radiation_imag,
                                             0);
   Vector rhs(layout.vector_size), solution(layout.vector_size);
   rhs = 0.0;
   solution = 0.0;
   double throat_area = 0.0;
   for (const auto &entry : throat.entries) { throat_area += entry.weight; }
   const double quadrant_fraction = quadrant_symmetry ? 0.25 : 1.0;
   const double derivative_imaginary =
      omega * density * volume_velocity * quadrant_fraction / throat_area;
   for (const auto &entry : throat.entries)
   {
      if (layout.owns(entry.pressure_dof))
      {
         rhs[layout.block_size + layout.local_pressure(entry.pressure_dof)] +=
            derivative_imaginary * entry.weight;
      }
   }

   MPI_Barrier(comm);
   const auto solve_start = std::chrono::steady_clock::now();
   KrylovResult result = fgmres(layout, system, preconditioner, rhs, solution,
                                1000, 100, 1e-8);
   const double solve_seconds = std::chrono::duration<double>(
      std::chrono::steady_clock::now() - solve_start).count();

   Vector pressure_real(solution.GetData(), layout.pressure_local);
   Vector pressure_imag(solution.GetData() + layout.block_size,
                        layout.pressure_local);
   Vector mouth_pressure_real, mouth_pressure_imag;
   layout.gather_trace(pressure_real, mouth, mouth_pressure_real);
   layout.gather_trace(pressure_imag, mouth, mouth_pressure_imag);
   Vector throat_pressure_real, throat_pressure_imag;
   layout.gather_trace(pressure_real, throat, throat_pressure_real);
   layout.gather_trace(pressure_imag, throat, throat_pressure_imag);

   double mouth_area = 0.0, radiated_power = 0.0;
   std::complex<double> average_throat_pressure = 0.0;
   for (int i = 0; i < mouth_size; ++i)
   {
      const std::complex<double> p(mouth_pressure_real[i], mouth_pressure_imag[i]);
      const std::complex<double> v(solution[layout.pressure_local + i],
         solution[layout.block_size + layout.pressure_local + i]);
      mouth_area += mouth.entries[i].weight;
      radiated_power += 0.5 * mouth.entries[i].weight * std::real(p * std::conj(v));
   }
   if (quadrant_symmetry) { radiated_power *= 4.0; }
   for (int i = 0; i < static_cast<int>(throat.entries.size()); ++i)
   {
      average_throat_pressure += throat.entries[i].weight *
         std::complex<double>(throat_pressure_real[i], throat_pressure_imag[i]);
   }
   average_throat_pressure /= throat_area;
   const std::complex<double> input_impedance =
      average_throat_pressure / volume_velocity;

   if (rank == 0 && !output_prefix.empty())
   {
      std::ofstream mouth_output(output_prefix + "_mouth.csv");
      mouth_output << std::setprecision(17)
                   << "x_m,y_m,z_m,area_weight_m2,pressure_real_pa,pressure_imag_pa,"
                      "normal_velocity_real_m_s,normal_velocity_imag_m_s\n";
      const int images = quadrant_symmetry ? 4 : 1;
      for (int i = 0; i < mouth_size; ++i)
      {
         for (int image = 0; image < images; ++image)
         {
            mouth_output << ((image & 1) ? -mouth.entries[i].x : mouth.entries[i].x)
                         << ',' << ((image & 2) ? -mouth.entries[i].y : mouth.entries[i].y)
                         << ',' << mouth.entries[i].z << ',' << mouth.entries[i].weight
                         << ',' << mouth_pressure_real[i] << ',' << mouth_pressure_imag[i]
                         << ',' << solution[layout.pressure_local + i] << ','
                         << solution[layout.block_size + layout.pressure_local + i]
                         << '\n';
         }
      }
      std::ofstream throat_output(output_prefix + "_throat.csv");
      throat_output << std::setprecision(17)
                    << "x_m,y_m,z_m,area_weight_m2,pressure_real_pa,pressure_imag_pa\n";
      for (int i = 0; i < static_cast<int>(throat.entries.size()); ++i)
      {
         for (int image = 0; image < images; ++image)
         {
            throat_output << ((image & 1) ? -throat.entries[i].x : throat.entries[i].x)
                          << ',' << ((image & 2) ? -throat.entries[i].y : throat.entries[i].y)
                          << ',' << throat.entries[i].z << ',' << throat.entries[i].weight
                          << ',' << throat_pressure_real[i] << ','
                          << throat_pressure_imag[i] << '\n';
         }
      }
      std::ofstream summary(output_prefix + "_summary.csv");
      summary << std::setprecision(17)
              << "frequency_hz,input_impedance_real_pa_s_m3,"
                 "input_impedance_imag_pa_s_m3,radiated_power_w,"
                 "gmres_iterations,solve_seconds,relative_residual\n"
              << frequency << ',' << input_impedance.real() << ','
              << input_impedance.imag() << ',' << radiated_power << ','
              << result.iterations << ',' << solve_seconds << ','
              << result.relative_residual << '\n';
   }
   if (rank == 0)
   {
      std::cout << "frequency_hz=" << frequency
                << " pressure_dofs=" << space.GlobalTrueVSize()
                << " mouth_dofs=" << mouth_size
                << " mpi_ranks=" << ranks
                << " input_impedance_real_pa_s_m3=" << input_impedance.real()
                << " input_impedance_imag_pa_s_m3=" << input_impedance.imag()
                << " radiated_power_w=" << radiated_power
                << " solver=distributed_fgmres_superlu_dist"
                << " symmetry=" << (quadrant_symmetry ? "quadrant" : "full")
                << " converged=" << result.converged
                << " iterations=" << result.iterations
                << " solve_seconds=" << solve_seconds
                << " relative_residual=" << result.relative_residual
                << std::endl;
   }
   return result.converged ? 0 : 1;
}
