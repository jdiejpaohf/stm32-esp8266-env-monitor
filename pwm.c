#include "pwm.h"

/*
通过PWM控制实现LED灯渐亮渐灭的过程:
1、查看原理图，确定LED灯对应的端口及引脚号(PA8)
2、确定引脚对应的第二功能是否有定时器 TIM1_CH1
封装初始化代码函数：
3、RCC硬件时钟使能 --> GPIOA, TIM1
4、GPIO_Init 初始化  --> GPIO_Mode 配置为 GPIO_Mode_AF_PP
5、TIM_TimeBaseInit --> 定时器基本参数的初始化
  特别注意：周期定时时长改为10ms即可
6、TIM_OC1Init --> 初始化定时器的OC通道1
  TIM_Pulse、TIM_OCMode、TIM_OCNPolarity、TIM_OutputState
7、TIM_Cmd --> 启动定时器工作
8、TIM_CtrlPWMOutputs --> 定时器的PWM使能
main函数中：
9、调用"初始化代码"函数
10、在主循环中调用 TIM_SetCompare1 函数，调整占空比
*/


void LEDPWM_TIM1CH1_Init(uint16_t arr, uint16_t psc)	// TIM_ARR寄存器（自动重载寄存器）、psc（Prescaler的缩写）
{
	// 定义一个外设的结构体变量
	GPIO_InitTypeDef GPIO_InitStructure;
	// 打开LED灯的外设时钟  PA8--GPIOA
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA, ENABLE);
	// 对结构体变量的成员进行赋值
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin_8;	// 引脚配置
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;	// 输出速率
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_AF_PP;	// 引脚模式   复用推挽输出
	// 初始化GPIO
	GPIO_Init(GPIOA, &GPIO_InitStructure);
	
	
	TIM_TimeBaseInitTypeDef TIM_TimeBaseInitStruct;
	// 打开TIM1的外设时钟   APB2	
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_TIM1, ENABLE);
	// 配置定时器TIM1的参数
	TIM_TimeBaseInitStruct.TIM_Period = arr-1;	// 计数周期（打算数多少次）：100   定时时长10毫秒
	TIM_TimeBaseInitStruct.TIM_Prescaler = psc -1;	// 预分频值（数数的快慢）   7200
	TIM_TimeBaseInitStruct.TIM_CounterMode = TIM_CounterMode_Up;	// 计数模式（打算怎么数）：递增计数
	TIM_TimeBaseInitStruct.TIM_ClockDivision = TIM_CKD_DIV1;	// 第二次分频系数
	TIM_TimeBaseInit(TIM1, &TIM_TimeBaseInitStruct);
	

	TIM_OCInitTypeDef TIM_OCInitStruct;
	TIM_OCInitStruct.TIM_Pulse = 50;	// 默认的占空比  默认50%
	TIM_OCInitStruct.TIM_OCMode = TIM_OCMode_PWM1;	// PWM模式1
	TIM_OCInitStruct.TIM_OCNPolarity = TIM_OCNPolarity_High;	// 输出极性高
	TIM_OCInitStruct.TIM_OutputState = TIM_OutputState_Enable;	// 使能输出比较
	// 初始化TIM_OC1
	TIM_OC1Init(TIM1, &TIM_OCInitStruct);
	
	// 使能定时器1工作
	TIM_Cmd(TIM1, ENABLE);
	
	// 使能TIM1的中断源，更新事件发生中断
	TIM_CtrlPWMOutputs(TIM1, ENABLE);
}
