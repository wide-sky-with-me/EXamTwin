---
fixture_id: oxfordaqa-mathematics-9660-2019-jan-p1-synthetic-v1
synthetic: true
real_student_response: false
subject_code: "9660"
pair_key: "9660:2019:JAN:P1"
unit_code: "P1"
intended_error_ids:
  - E01
  - E02
  - E03
  - E04
  - E05
---

# Q1

**(a)(i)** Setting $y=0$ in $3x-2y+5=0$ gives

$$3x+5=0 \quad\Rightarrow\quad x=-\frac{5}{3}.$$

**(a)(ii)** Rearranging,

$$y=\frac{3}{2}x+\frac{5}{2},$$

so the gradient is $\frac{3}{2}$.

**(b)** A perpendicular line has gradient $-\frac{2}{3}$ and the same $y$-intercept.

$$\boxed{y=-\frac{2}{3}x+\frac{5}{2}}$$

# Q2

**(a)**

$$p=(16a^{20}b^8)^{1/4}=\boxed{2a^5b^2}.$$

**(b)** Since $y=\sqrt[3]{x}=x^{1/3}$,

$$z=\left(\frac{x}{y}\right)^2
=\left(\frac{x}{x^{1/3}}\right)^2
=\boxed{x^{2/3}}.$$

# Q3

**(a)**

$$
f(x)=2(x^2-8x)+38
=2\big((x-4)^2-16\big)+38
=\boxed{2(x-4)^2+6}.
$$

**(b)** The graph is an upward-opening parabola with vertex $B=(4,6)$ and $y$-intercept
$A=(0,38)$. Its axis of symmetry is $x=4$.

**(c)(i)** At an intersection with $y=4x+20$,

$$2x^2-16x+38=4x+20,$$

so

$$2x^2-20x+18=0 \quad\Rightarrow\quad \boxed{x^2-10x+9=0}.$$

**(c)(ii)** The roots are $x=1$ and $x=9$, giving $P=(1,24)$ and $Q=(9,56)$.

$$PQ=\sqrt{(9-1)^2+(56-24)^2}
=\sqrt{1088}
=\boxed{8\sqrt{17}}.$$

# Q4

**(a)** For $(1-3x)^6$,

$$p=\binom{6}{2}(-3)^2=15\times9=135,$$

and

$$q=\binom{6}{3}(-3)^3=20\times(-27)=\boxed{-540}.$$

**(b)** The coefficient of $x^3$ in
$\left(1+\frac{x}{5}\right)(1-3x)^6$ is

$$-540+\frac{135}{5}=-540+27=\boxed{-513}.$$

# Q5

**(a)**

$$\frac{dy}{dx}=3x^2+4x-15.$$

At $x=2$, the tangent gradient is $5$, so the normal gradient is $-\frac15$.

$$y-6=-\frac15(x-2)
\quad\Rightarrow\quad
\boxed{y=-\frac15x+\frac{32}{5}}.$$

**(b)(i)** At $x=-3$,

$$3(-3)^2+4(-3)-15=27-12-15=0,$$

so $A$ is stationary.

**(b)(ii)**

$$\frac{d^2y}{dx^2}=6x+4,$$

hence at $A$, $\frac{d^2y}{dx^2}=-18+4=\boxed{-14}$.

**(b)(iii)** Since the second derivative is negative, $A$ is a
$\boxed{\text{minimum}}$.

**(c)** The derivative is negative between its roots $-3$ and $\frac53$, so

$$\boxed{-3<x<\frac53}.$$

# Q6

**(a)** With four ordinates on $[0.5,2]$, $h=0.5$. For $f(x)=1+0.3^x$,

$$
\begin{aligned}
f(0.5)&=1.547722\ldots,\\
f(1)&=1.3,\\
f(1.5)&=1.164317\ldots,\\
f(2)&=1.09.
\end{aligned}
$$

Therefore

$$
I\approx\frac{0.5}{2}
\left[f(0.5)+2f(1)+2f(1.5)+f(2)\right]
=1.89159\ldots
=\boxed{1.892}.
$$

**(b)(i)** This is an $\boxed{\text{under-estimate}}$ because the curve lies above the
tops of the trapezia.

**(b)(ii)** Use more, narrower trapezia (increase the number of ordinates).

# Q7

**(a)** Translating by $\begin{pmatrix}1\\4\end{pmatrix}$ gives

$$
y=2a(x-1)^3-7b(x-1)+4.
$$

Expanding,

$$
\boxed{y=2ax^3-6ax^2+(6a-7b)x-2a+7b+4}.
$$

**(b)** Since $P=(2,8)$ is on the curve,

$$2a-7b=4. \tag{1}$$

Also

$$\frac{dy}{dx}=6ax^2-12ax+6a-7b.$$

At $x=2$, the gradient is $20$, so

$$6a-7b=20. \tag{2}$$

Subtracting (1) from (2) gives $4a=16$, hence

$$\boxed{a=4}, \qquad \boxed{b=\frac47}.$$

# Q8

**(a)** For the arithmetic sequence,

$$u_n=3+(n-1)d.$$

From $u_5=p+4$,

$$3+4d=p+4 \quad\Rightarrow\quad 4d=p+1. \tag{1}$$

Also

$$u_9=3+8d=(2p-1)^2.$$

Using (1), $3+8d=2p+5$, so

$$2p+5=4p^2-4p+1
\quad\Rightarrow\quad
\boxed{2p^2-3p-2=0}.
$$

**(b)(i)**

$$2p^2-3p-2=(2p+1)(p-2)=0.$$

Since $p>0$, $p=2$, and therefore

$$d=\frac{p+1}{4}=\boxed{\frac34}.$$

**(b)(ii)**

$$
S_k=\frac{k}{2}\left(6+(k-1)\frac34\right)=138.
$$

Thus

$$3k(k+7)=1104
\quad\Rightarrow\quad
k^2+7k-368=0.
$$

Taking the positive root gives $\boxed{k=15}$.

# Q9

**(a)** By the Remainder Theorem,

$$p(-2)=-8+4a+2-21=-7.$$

Hence $4a-27=-7$, so $\boxed{a=5}$.

**(b)**

$$p(-3)=-27+5(9)+3-21=0,$$

therefore $(x+3)$ is a factor.

**(c)**

$$x^3+5x^2-x-21=(x+3)(x^2+2x-7).$$

For $x>0$,

$$
\int\frac{x^3+5x^2-x-21}{x(x+3)}\,dx
=\int\left(x+2-\frac7x\right)dx
=\boxed{\frac{x^2}{2}+2x-7\ln x+C}.
$$

# Q10

**(a)** The positive common ratio is

$$r=k^4-4k^2-11.$$

The sum to infinity does not exist when $r\ge1$, so

$$k^4-4k^2-11\ge1.$$

Putting $y=k^2$ gives

$$\boxed{y^2-4y-12\ge0}.$$

**(b)**

$$y^2-4y-12=(y-6)(y+2)\ge0.$$

Since $y=k^2\ge0$, the branch $y\le-2$ is impossible, leaving $k^2\ge6$.
Therefore

$$\boxed{k\ge\sqrt6}.$$
