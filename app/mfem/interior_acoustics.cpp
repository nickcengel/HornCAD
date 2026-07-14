// Native reference for the reduced HornCAD interior/aperture formulation.
#include <mfem.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <complex>
#include <iostream>
#include <map>
#include <string>
#include <vector>

using namespace mfem;

namespace
{
constexpr double pi = 3.14159265358979323846;

struct BoundaryTrace
{
   std::vector<int> dofs;
   std::vector<Vector> points;
   std::vector<double> weights;
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

BoundaryTrace boundary_trace(Mesh &mesh, FiniteElementSpace &fes, int attribute)
{
   std::map<int, double> weights_by_dof;
   std::map<int, Vector> points_by_dof;
   Array<int> vertices;
   for (int element = 0; element < mesh.GetNBE(); ++element)
   {
      if (mesh.GetBdrAttribute(element) != attribute) { continue; }
      mesh.GetBdrElementVertices(element, vertices);
      MFEM_VERIFY(vertices.Size() == 3, "aperture boundaries must be triangular");
      const double *a = mesh.GetVertex(vertices[0]);
      const double *b = mesh.GetVertex(vertices[1]);
      const double *c = mesh.GetVertex(vertices[2]);
      const double share = triangle_area(a, b, c) / 3.0;
      for (int local = 0; local < 3; ++local)
      {
         const int dof = vertex_dof(fes, vertices[local]);
         weights_by_dof[dof] += share;
         Vector point(3);
         const double *coordinates = mesh.GetVertex(vertices[local]);
         for (int axis = 0; axis < 3; ++axis) { point[axis] = coordinates[axis]; }
         points_by_dof[dof] = point;
      }
   }
   BoundaryTrace trace;
   for (const auto &[dof, weight] : weights_by_dof)
   {
      trace.dofs.push_back(dof);
      trace.points.push_back(points_by_dof[dof]);
      trace.weights.push_back(weight);
   }
   MFEM_VERIFY(!trace.dofs.empty(), "requested boundary attribute is empty");
   return trace;
}

class MixedRealOperator : public Operator
{
private:
   const SparseMatrix &pressure_;
   const BoundaryTrace &mouth_;
   const DenseMatrix &radiation_;
   int pressure_size_;

public:
   MixedRealOperator(const SparseMatrix &pressure, const BoundaryTrace &mouth,
                     const DenseMatrix &radiation)
      : Operator(pressure.Height() + radiation.Height()), pressure_(pressure),
        mouth_(mouth), radiation_(radiation), pressure_size_(pressure.Height()) { }

   void Mult(const Vector &x, Vector &y) const override
   {
      y = 0.0;
      Vector pressure_in(const_cast<double *>(x.GetData()), pressure_size_);
      Vector pressure_out(y.GetData(), pressure_size_);
      pressure_.Mult(pressure_in, pressure_out);
      Vector velocity_in(const_cast<double *>(x.GetData()) + pressure_size_,
                         radiation_.Width());
      Vector aperture_out(y.GetData() + pressure_size_, radiation_.Height());
      radiation_.Mult(velocity_in, aperture_out);
      for (int local = 0; local < radiation_.Height(); ++local)
      {
         aperture_out[local] -= pressure_in[mouth_.dofs[local]];
      }
   }
};

class MixedImagOperator : public Operator
{
private:
   const BoundaryTrace &mouth_;
   const DenseMatrix &radiation_;
   int pressure_size_;
   double coupling_;

public:
   MixedImagOperator(int pressure_size, const BoundaryTrace &mouth,
                     const DenseMatrix &radiation, double coupling)
      : Operator(pressure_size + radiation.Height()), mouth_(mouth),
        radiation_(radiation), pressure_size_(pressure_size), coupling_(coupling) { }

   void Mult(const Vector &x, Vector &y) const override
   {
      y = 0.0;
      Vector velocity_in(const_cast<double *>(x.GetData()) + pressure_size_,
                         radiation_.Width());
      Vector aperture_out(y.GetData() + pressure_size_, radiation_.Height());
      radiation_.Mult(velocity_in, aperture_out);
      for (int local = 0; local < radiation_.Height(); ++local)
      {
         y[mouth_.dofs[local]] += coupling_ * mouth_.weights[local] * velocity_in[local];
      }
   }
};

class MixedBlockPreconditioner : public Solver
{
private:
   UMFPackSolver pressure_solver_;
   DenseMatrix radiation_real_;
   DenseMatrix radiation_imag_;
   Array<int> pivots_;
   ComplexLUFactors radiation_solver_;
   int pressure_size_;
   int system_size_;

public:
   MixedBlockPreconditioner(SparseMatrix &pressure, const DenseMatrix &radiation_real,
                            const DenseMatrix &radiation_imag)
      : Solver(2 * (pressure.Height() + radiation_real.Height())),
        pressure_solver_(pressure), radiation_real_(radiation_real),
        radiation_imag_(radiation_imag), pivots_(radiation_real.Height()),
        pressure_size_(pressure.Height()),
        system_size_(pressure.Height() + radiation_real.Height())
   {
      radiation_solver_.data_r = radiation_real_.Data();
      radiation_solver_.data_i = radiation_imag_.Data();
      radiation_solver_.ipiv = pivots_.GetData();
      MFEM_VERIFY(radiation_solver_.Factor(radiation_real_.Height()),
                  "aperture impedance factorization failed");
   }

   void SetOperator(const Operator &op) override
   {
      MFEM_VERIFY(op.Height() == Height(), "preconditioner size cannot change");
   }

   void Mult(const Vector &x, Vector &y) const override
   {
      y = 0.0;
      Vector input_real(const_cast<double *>(x.GetData()), pressure_size_);
      Vector output_real(y.GetData(), pressure_size_);
      Vector input_imag(const_cast<double *>(x.GetData()) + system_size_, pressure_size_);
      Vector output_imag(y.GetData() + system_size_, pressure_size_);
      pressure_solver_.Mult(input_real, output_real);
      pressure_solver_.Mult(input_imag, output_imag);
      const int mouth_size = radiation_real_.Height();
      Vector aperture_real(y.GetData() + pressure_size_, mouth_size);
      Vector aperture_imag(y.GetData() + system_size_ + pressure_size_, mouth_size);
      for (int local = 0; local < mouth_size; ++local)
      {
         aperture_real[local] = x[pressure_size_ + local];
         aperture_imag[local] = x[system_size_ + pressure_size_ + local];
      }
      radiation_solver_.Solve(mouth_size, 1, aperture_real.GetData(),
                              aperture_imag.GetData());
   }
};
} // namespace

int main(int argc, char *argv[])
{
   Mpi::Init(argc, argv);
   if (argc < 3)
   {
      std::cerr << "usage: horncad_mfem_interior MESH.msh FREQUENCY_HZ\n";
      return 2;
   }
   const std::string mesh_path = argv[1];
   const double frequency = std::stod(argv[2]);
   MFEM_VERIFY(frequency > 0.0, "frequency must be positive");
   constexpr double density = 1.2041;
   constexpr double sound_speed = 343.21;
   constexpr double volume_velocity = 1.0;
   const double omega = 2.0 * pi * frequency;
   const double wave_number = omega / sound_speed;

   Mesh mesh(mesh_path.c_str(), 1, 1);
   H1_FECollection collection(1, mesh.Dimension());
   FiniteElementSpace space(&mesh, &collection);
   ConstantCoefficient negative_k_squared(-wave_number * wave_number);
   BilinearForm helmholtz(&space);
   helmholtz.AddDomainIntegrator(new DiffusionIntegrator);
   helmholtz.AddDomainIntegrator(new MassIntegrator(negative_k_squared));
   helmholtz.Assemble();
   helmholtz.Finalize();

   const BoundaryTrace throat = boundary_trace(mesh, space, 2);
   const BoundaryTrace mouth = boundary_trace(mesh, space, 3);
   const int pressure_size = space.GetVSize();
   const int mouth_size = static_cast<int>(mouth.dofs.size());
   const int system_size = pressure_size + mouth_size;
   DenseMatrix radiation_real(mouth_size), radiation_imag(mouth_size);
   for (int row = 0; row < mouth_size; ++row)
   {
      for (int column = 0; column < mouth_size; ++column)
      {
         std::complex<double> integral;
         if (row == column)
         {
            const double radius = std::sqrt(mouth.weights[column] / pi);
            integral = 2.0 * pi *
                       (1.0 - std::exp(std::complex<double>(0.0, -wave_number * radius))) /
                       std::complex<double>(0.0, wave_number);
         }
         else
         {
            double distance_squared = 0.0;
            for (int axis = 0; axis < 3; ++axis)
            {
               const double delta = mouth.points[row][axis] - mouth.points[column][axis];
               distance_squared += delta * delta;
            }
            const double distance = std::sqrt(distance_squared);
            integral = mouth.weights[column] *
                       std::exp(std::complex<double>(0.0, -wave_number * distance)) /
                       distance;
         }
         const std::complex<double> impedance =
            std::complex<double>(0.0, density * omega / (2.0 * pi)) * integral;
         radiation_real(row, column) = impedance.real();
         radiation_imag(row, column) = impedance.imag();
      }
   }
   MixedRealOperator real(helmholtz.SpMat(), mouth, radiation_real);
   MixedImagOperator imag(pressure_size, mouth, radiation_imag, omega * density);
   ComplexOperator system(&real, &imag, false, false);
   MixedBlockPreconditioner preconditioner(helmholtz.SpMat(), radiation_real,
                                           radiation_imag);

   Vector rhs(2 * system_size), solution(2 * system_size);
   rhs = 0.0;
   solution = 0.0;
   double throat_area = 0.0;
   for (double weight : throat.weights) { throat_area += weight; }
   const double derivative_imaginary = omega * density * volume_velocity / throat_area;
   for (int local = 0; local < static_cast<int>(throat.dofs.size()); ++local)
   {
      rhs[system_size + throat.dofs[local]] +=
         derivative_imaginary * throat.weights[local];
   }
   GMRESSolver solver;
   solver.SetOperator(system);
   solver.SetPreconditioner(preconditioner);
   // The preconditioned residual understates the physical-system residual by
   // several orders of magnitude for this mixed scaling.
   solver.SetRelTol(1e-12);
   solver.SetAbsTol(0.0);
   solver.SetMaxIter(1000);
   solver.SetKDim(100);
   solver.SetPrintLevel(0);
   const auto solve_start = std::chrono::steady_clock::now();
   solver.Mult(rhs, solution);
   const double solve_seconds = std::chrono::duration<double>(
      std::chrono::steady_clock::now() - solve_start).count();

   Vector residual(2 * system_size);
   system.Mult(solution, residual);
   residual -= rhs;
   double mouth_area = 0.0, radiated_power = 0.0;
   for (int local = 0; local < mouth_size; ++local)
   {
      const int pressure_dof = mouth.dofs[local];
      const int velocity_dof = pressure_size + local;
      const std::complex<double> pressure(solution[pressure_dof],
                                          solution[system_size + pressure_dof]);
      const std::complex<double> velocity(solution[velocity_dof],
                                          solution[system_size + velocity_dof]);
      mouth_area += mouth.weights[local];
      radiated_power += 0.5 * mouth.weights[local] *
                        std::real(pressure * std::conj(velocity));
   }
   std::cout << "frequency_hz=" << frequency
             << " pressure_dofs=" << pressure_size
             << " mouth_dofs=" << mouth_size
             << " throat_area_m2=" << throat_area
             << " mouth_area_m2=" << mouth_area
             << " radiated_power_w=" << radiated_power
             << " solver=matrix_free_gmres"
             << " converged=" << solver.GetConverged()
             << " iterations=" << solver.GetNumIterations()
             << " solve_seconds=" << solve_seconds
             << " relative_residual=" << residual.Norml2() / rhs.Norml2()
             << std::endl;
   return 0;
}
